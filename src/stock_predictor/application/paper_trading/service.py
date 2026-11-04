"""Transactional paper-account application service with no broker boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from stock_predictor.application.operations.audit import AuditEventFactory
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import (
    AuthorizationError,
    DomainConflictError,
    IdempotencyConflictError,
    PaperTradingError,
)
from stock_predictor.domain.common.identifiers import (
    OutboxEventId,
    PaperAccountId,
    PaperFillId,
    PaperOrderId,
)
from stock_predictor.domain.common.money import Currency, Money
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal
from stock_predictor.domain.operations.paper import (
    PaperAccount,
    PaperExecution,
    PaperFill,
    PaperOrder,
    PaperOrderSide,
    PaperTradeRequest,
    execution_price,
)
from stock_predictor.domain.operations.records import (
    AuditOutcome,
    IdempotencyRecord,
    IdempotencyStatus,
    JsonDocument,
    OutboxEvent,
)
from stock_predictor.domain.security.identity import Principal, PrincipalRole
from stock_predictor.ports.operational_store import (
    OperationalUnitOfWork,
    OperationalUnitOfWorkFactory,
)
from stock_predictor.ports.telemetry import Telemetry


@dataclass(frozen=True, slots=True)
class PaperTradingPolicy:
    spread_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("2")
    commission_bps: Decimal = Decimal("1")
    fixed_commission: Decimal = Decimal("0")
    maximum_order_notional: Decimal = Decimal("1000000")
    maximum_position_notional: Decimal = Decimal("2000000")
    maximum_price_age: timedelta = timedelta(minutes=30)
    idempotency_ttl: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        values = (
            self.spread_bps,
            self.slippage_bps,
            self.commission_bps,
            self.fixed_commission,
            self.maximum_order_notional,
            self.maximum_position_notional,
        )
        if any(item < 0 for item in values):
            raise ValueError("Paper-trading policy values cannot be negative")
        if self.maximum_order_notional <= 0 or self.maximum_position_notional <= 0:
            raise ValueError("Paper-trading notional limits must be positive")
        if self.maximum_price_age <= timedelta(0) or self.idempotency_ttl <= timedelta(0):
            raise ValueError("Paper-trading time limits must be positive")


class PaperTradingService:
    def __init__(
        self,
        store: OperationalUnitOfWorkFactory,
        clock: Clock,
        telemetry: Telemetry,
        *,
        policy: PaperTradingPolicy | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._telemetry = telemetry
        self._policy = policy or PaperTradingPolicy()
        self._audit = AuditEventFactory(clock)

    def open_account(
        self,
        *,
        principal: Principal,
        name: str,
        initial_cash: DecimalInput,
        currency: Currency,
        idempotency_key: str,
        correlation_id: str,
        request_id: str,
    ) -> PaperAccount:
        principal.require_any(PrincipalRole.OPERATOR, PrincipalRole.ADMIN)
        request_hash = _request_hash(
            {
                "name": name.strip(),
                "initial_cash": str(
                    to_decimal(initial_cash, field_name="initial paper cash")
                ),
                "currency": str(currency),
            }
        )
        operation = "paper.account.open"
        now = self._clock.now()
        with self._store() as uow:
            existing = uow.idempotency.get(
                principal_id=principal.subject,
                operation=operation,
                key=idempotency_key,
            )
            replay = self._resolve_account_replay(
                uow,
                existing,
                request_hash=request_hash,
            )
            if replay is not None:
                return replay
            record = IdempotencyRecord(
                key=idempotency_key,
                principal_id=principal.subject,
                operation=operation,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING,
                created_at=now,
                expires_at=now.plus(self._policy.idempotency_ttl),
            )
            uow.idempotency.add(record)
            account = PaperAccount.open(
                account_id=PaperAccountId.new(),
                owner_subject=principal.subject,
                name=name,
                initial_cash=initial_cash,
                currency=currency,
                opened_at=now,
            )
            uow.paper.add_account(account)
            audit = self._audit.create(
                uow.audit,
                actor_id=principal.subject,
                action="paper.account.open",
                resource_type="paper.account",
                resource_id=str(account.account_id),
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                request_id=request_id,
                reason="Paper account opened by authorized operator",
                attributes={
                    "currency": str(currency),
                    "initial_cash": str(account.cash.amount),
                },
            )
            uow.audit.append(audit)
            uow.outbox.add(
                OutboxEvent(
                    event_id=OutboxEventId.new(),
                    aggregate_type="paper.account",
                    aggregate_id=str(account.account_id),
                    event_type="paper.account.opened",
                    event_version=1,
                    occurred_at=now,
                    available_at=now,
                    payload=JsonDocument.from_mapping(
                        {
                            "account_id": str(account.account_id),
                            "owner_subject": account.owner_subject,
                            "currency": str(currency),
                        }
                    ),
                    correlation_id=correlation_id,
                    causation_id=request_id,
                )
            )
            completed = record.complete(
                response_status=201,
                response=JsonDocument.from_mapping(
                    {"account_id": str(account.account_id)}
                ),
            )
            uow.idempotency.save(completed, expected_revision=record.revision)
            uow.commit()
        return account

    def execute_order(
        self,
        *,
        principal: Principal,
        request: PaperTradeRequest,
        correlation_id: str,
        request_id: str,
    ) -> PaperExecution:
        principal.require_any(PrincipalRole.OPERATOR, PrincipalRole.ADMIN)
        operation = "paper.order.execute"
        now = self._clock.now()
        self._validate_price_time(request, now)
        with self._store() as uow:
            existing = uow.idempotency.get(
                principal_id=principal.subject,
                operation=operation,
                key=request.idempotency_key,
            )
            replay = self._resolve_order_replay(
                uow,
                existing,
                request_hash=request.request_hash,
            )
            if replay is not None:
                self._telemetry.record_paper_order(
                    side=replay.order.side.value,
                    outcome="replayed",
                )
                return replay
            account = uow.paper.get_account(request.account_id)
            self._authorize_account(principal, account)
            record = IdempotencyRecord(
                key=request.idempotency_key,
                principal_id=principal.subject,
                operation=operation,
                request_hash=request.request_hash,
                status=IdempotencyStatus.PROCESSING,
                created_at=now,
                expires_at=now.plus(self._policy.idempotency_ttl),
            )
            uow.idempotency.add(record)
            execution = self._build_execution(account, request, now)
            uow.paper.save_account(
                execution.account,
                expected_revision=account.revision,
            )
            uow.paper.add_order(execution.order)
            uow.paper.add_fill(execution.fill)
            self._append_order_evidence(
                uow,
                principal=principal,
                execution=execution,
                correlation_id=correlation_id,
                request_id=request_id,
                occurred_at=now,
            )
            completed = record.complete(
                response_status=201,
                response=JsonDocument.from_mapping(
                    {
                        "account_id": str(execution.account.account_id),
                        "order_id": str(execution.order.order_id),
                    }
                ),
            )
            uow.idempotency.save(completed, expected_revision=record.revision)
            uow.commit()
        self._telemetry.record_paper_order(side=request.side.value, outcome="filled")
        return execution

    def get_account(self, principal: Principal, account_id: PaperAccountId) -> PaperAccount:
        principal.require_any(
            PrincipalRole.VIEWER,
            PrincipalRole.OPERATOR,
            PrincipalRole.AUDITOR,
            PrincipalRole.ADMIN,
        )
        with self._store() as uow:
            account = uow.paper.get_account(account_id)
        self._authorize_account(principal, account, allow_auditor=True)
        return account

    def list_accounts(self, principal: Principal) -> tuple[PaperAccount, ...]:
        principal.require_any(
            PrincipalRole.VIEWER,
            PrincipalRole.OPERATOR,
            PrincipalRole.AUDITOR,
            PrincipalRole.ADMIN,
        )
        owner = None if PrincipalRole.ADMIN in principal.roles else principal.subject
        if PrincipalRole.AUDITOR in principal.roles:
            owner = None
        with self._store() as uow:
            return uow.paper.list_accounts(owner_subject=owner)

    def list_orders(
        self,
        principal: Principal,
        account_id: PaperAccountId,
    ) -> tuple[PaperOrder, ...]:
        account = self.get_account(principal, account_id)
        with self._store() as uow:
            orders = uow.paper.list_orders(account.account_id)
        return orders

    def _build_execution(
        self,
        account: PaperAccount,
        request: PaperTradeRequest,
        now: UtcInstant,
    ) -> PaperExecution:
        price = execution_price(
            request.reference_price,
            request.side,
            spread_bps=self._policy.spread_bps,
            slippage_bps=self._policy.slippage_bps,
        )
        gross = Money(price.amount * request.quantity.value, price.currency)
        if gross.amount > self._policy.maximum_order_notional:
            raise PaperTradingError("Paper order exceeds maximum notional")
        commission = Money(
            self._policy.fixed_commission
            + gross.amount * self._policy.commission_bps / Decimal(10_000),
            price.currency,
        )
        order = PaperOrder(
            order_id=PaperOrderId.new(),
            account_id=account.account_id,
            instrument_id=request.instrument_id,
            side=request.side,
            quantity=request.quantity,
            reference_price=request.reference_price,
            submitted_at=now,
            idempotency_key=request.idempotency_key,
            request_hash=request.request_hash,
        )
        fill = PaperFill(
            fill_id=PaperFillId.new(),
            order_id=order.order_id,
            account_id=account.account_id,
            instrument_id=request.instrument_id,
            side=request.side,
            quantity=request.quantity,
            reference_price=request.reference_price,
            execution_price=price,
            gross_notional=gross,
            commission=commission,
            filled_at=now,
        )
        updated = account.apply_fill(fill)
        position = updated.position(request.instrument_id)
        if position is not None:
            position_notional = position.quantity.value * price.amount
            if position_notional > self._policy.maximum_position_notional:
                raise PaperTradingError("Paper position exceeds maximum notional")
        return PaperExecution(updated, order, fill)

    def _append_order_evidence(
        self,
        uow: OperationalUnitOfWork,
        *,
        principal: Principal,
        execution: PaperExecution,
        correlation_id: str,
        request_id: str,
        occurred_at: UtcInstant,
    ) -> None:
        audit = self._audit.create(
            uow.audit,
            actor_id=principal.subject,
            action="paper.order.execute",
            resource_type="paper.order",
            resource_id=str(execution.order.order_id),
            outcome=AuditOutcome.SUCCESS,
            correlation_id=correlation_id,
            request_id=request_id,
            reason="Paper order executed under configured simulation policy",
            attributes={
                "account_id": str(execution.account.account_id),
                "instrument_id": str(execution.order.instrument_id),
                "side": execution.order.side.value,
                "quantity": str(execution.order.quantity.value),
                "execution_price": str(execution.fill.execution_price.amount),
                "commission": str(execution.fill.commission.amount),
            },
        )
        uow.audit.append(audit)
        uow.outbox.add(
            OutboxEvent(
                event_id=OutboxEventId.new(),
                aggregate_type="paper.order",
                aggregate_id=str(execution.order.order_id),
                event_type="paper.order.filled",
                event_version=1,
                occurred_at=occurred_at,
                available_at=occurred_at,
                payload=JsonDocument.from_mapping(
                    {
                        "account_id": str(execution.account.account_id),
                        "order_id": str(execution.order.order_id),
                        "instrument_id": str(execution.order.instrument_id),
                        "side": execution.order.side.value,
                    }
                ),
                correlation_id=correlation_id,
                causation_id=request_id,
            )
        )

    def _resolve_account_replay(
        self,
        uow: OperationalUnitOfWork,
        existing: IdempotencyRecord | None,
        *,
        request_hash: str,
    ) -> PaperAccount | None:
        if existing is None:
            return None
        self._validate_replay(existing, request_hash)
        response = existing.response.as_dict() if existing.response else {}
        account_id = response.get("account_id")
        if not isinstance(account_id, str):
            raise DomainConflictError("Completed account request lacks account identity")
        return uow.paper.get_account(PaperAccountId.parse(account_id))

    def _resolve_order_replay(
        self,
        uow: OperationalUnitOfWork,
        existing: IdempotencyRecord | None,
        *,
        request_hash: str,
    ) -> PaperExecution | None:
        if existing is None:
            return None
        self._validate_replay(existing, request_hash)
        response = existing.response.as_dict() if existing.response else {}
        account_id = response.get("account_id")
        order_id = response.get("order_id")
        if not isinstance(account_id, str) or not isinstance(order_id, str):
            raise DomainConflictError("Completed paper order lacks replay identities")
        account = uow.paper.get_account(PaperAccountId.parse(account_id))
        order = uow.paper.get_order(PaperOrderId.parse(order_id))
        fills = tuple(
            item
            for item in uow.paper.list_fills(account.account_id)
            if item.order_id == order.order_id
        )
        if len(fills) != 1:
            raise DomainConflictError("Completed paper order lacks one persisted fill")
        return PaperExecution(account, order, fills[0])

    @staticmethod
    def _validate_replay(existing: IdempotencyRecord, request_hash: str) -> None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "Idempotency key was already used for a different request"
            )
        if existing.status is not IdempotencyStatus.COMPLETED:
            raise DomainConflictError("Idempotent request is not in a replayable state")

    def _validate_price_time(
        self,
        request: PaperTradeRequest,
        now: UtcInstant,
    ) -> None:
        if request.price_observed_at > now:
            raise PaperTradingError("Paper reference price cannot come from the future")
        if now.value - request.price_observed_at.value > self._policy.maximum_price_age:
            raise PaperTradingError("Paper reference price is stale")

    @staticmethod
    def _authorize_account(
        principal: Principal,
        account: PaperAccount,
        *,
        allow_auditor: bool = False,
    ) -> None:
        privileged = PrincipalRole.ADMIN in principal.roles
        if allow_auditor and PrincipalRole.AUDITOR in principal.roles:
            privileged = True
        if account.owner_subject != principal.subject and not privileged:
            raise AuthorizationError("Principal cannot access another paper account")


def _request_hash(payload: dict[str, str]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
