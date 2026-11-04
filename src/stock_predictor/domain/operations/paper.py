"""Paper-only account, order, fill, and accounting invariants."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError, PaperTradingError
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    PaperAccountId,
    PaperFillId,
    PaperOrderId,
)
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, Quantity, to_decimal

_ACCOUNT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{1,79}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._~:+/=-]{8,200}$")


class PaperOrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PaperOrderStatus(StrEnum):
    FILLED = "filled"


@dataclass(frozen=True, slots=True)
class PaperPosition:
    instrument_id: InstrumentId
    quantity: Quantity
    average_price: Price

    def __post_init__(self) -> None:
        if self.quantity.value <= 0:
            raise DomainValidationError("Paper position quantity must be positive")


@dataclass(frozen=True, slots=True)
class PaperAccount:
    """Versioned paper account; no broker or live-capital concept exists."""

    account_id: PaperAccountId
    owner_subject: str
    name: str
    base_currency: Currency
    cash: Money
    realized_pnl: Money
    positions: tuple[PaperPosition, ...]
    revision: int
    created_at: UtcInstant
    updated_at: UtcInstant

    def __post_init__(self) -> None:
        owner = self.owner_subject.strip()
        name = self.name.strip()
        if not owner or not _ACCOUNT_NAME.fullmatch(name):
            raise DomainValidationError("Paper account owner or name is invalid")
        if self.cash.currency != self.base_currency:
            raise DomainValidationError("Paper account cash currency must match base currency")
        if self.realized_pnl.currency != self.base_currency:
            raise DomainValidationError("Realized P&L currency must match base currency")
        if self.cash.amount < 0 or self.revision <= 0:
            raise DomainValidationError("Paper account cash and revision are invalid")
        if self.updated_at < self.created_at:
            raise DomainValidationError("Paper account update cannot predate creation")
        ids = tuple(item.instrument_id for item in self.positions)
        if len(set(ids)) != len(ids):
            raise DomainValidationError("Paper account positions must be unique")
        if any(item.average_price.currency != self.base_currency for item in self.positions):
            raise DomainValidationError("Paper positions must use the account currency")
        object.__setattr__(self, "owner_subject", owner)
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "positions",
            tuple(sorted(self.positions, key=lambda item: str(item.instrument_id))),
        )

    @classmethod
    def open(
        cls,
        *,
        account_id: PaperAccountId,
        owner_subject: str,
        name: str,
        initial_cash: DecimalInput,
        currency: Currency,
        opened_at: UtcInstant,
    ) -> PaperAccount:
        cash = Money(initial_cash, currency)
        if cash.amount <= 0:
            raise DomainValidationError("Initial paper cash must be positive")
        return cls(
            account_id=account_id,
            owner_subject=owner_subject,
            name=name,
            base_currency=currency,
            cash=cash,
            realized_pnl=Money.zero(currency),
            positions=(),
            revision=1,
            created_at=opened_at,
            updated_at=opened_at,
        )

    def position(self, instrument_id: InstrumentId) -> PaperPosition | None:
        return next(
            (item for item in self.positions if item.instrument_id == instrument_id),
            None,
        )

    def apply_fill(self, fill: PaperFill) -> PaperAccount:
        if fill.account_id != self.account_id:
            raise PaperTradingError("Paper fill belongs to another account")
        if fill.execution_price.currency != self.base_currency:
            raise PaperTradingError("Paper fill currency differs from the account")
        if fill.filled_at < self.updated_at:
            raise PaperTradingError("Paper fill cannot predate the account revision")
        if fill.side is PaperOrderSide.BUY:
            return self._apply_buy(fill)
        return self._apply_sell(fill)

    def _apply_buy(self, fill: PaperFill) -> PaperAccount:
        debit = fill.gross_notional + fill.commission
        if debit.amount > self.cash.amount:
            raise PaperTradingError("Insufficient paper cash for buy order")
        current = self.position(fill.instrument_id)
        existing_quantity = current.quantity.value if current is not None else Decimal(0)
        existing_cost = (
            current.average_price.amount * existing_quantity
            if current is not None
            else Decimal(0)
        )
        new_quantity = existing_quantity + fill.quantity.value
        average = (existing_cost + fill.gross_notional.amount) / new_quantity
        position = PaperPosition(
            fill.instrument_id,
            Quantity(new_quantity),
            Price(average, self.base_currency),
        )
        positions = self._replace_position(position)
        return replace(
            self,
            cash=self.cash - debit,
            positions=positions,
            revision=self.revision + 1,
            updated_at=fill.filled_at,
        )

    def _apply_sell(self, fill: PaperFill) -> PaperAccount:
        current = self.position(fill.instrument_id)
        if current is None or current.quantity.value < fill.quantity.value:
            raise PaperTradingError("Short selling is disabled for paper accounts")
        remaining = current.quantity.value - fill.quantity.value
        positions = tuple(
            item for item in self.positions if item.instrument_id != fill.instrument_id
        )
        if remaining > 0:
            positions += (
                PaperPosition(
                    fill.instrument_id,
                    Quantity(remaining),
                    current.average_price,
                ),
            )
        credit = fill.gross_notional - fill.commission
        realized = Money(
            (fill.execution_price.amount - current.average_price.amount)
            * fill.quantity.value
            - fill.commission.amount,
            self.base_currency,
        )
        return replace(
            self,
            cash=self.cash + credit,
            realized_pnl=self.realized_pnl + realized,
            positions=tuple(sorted(positions, key=lambda item: str(item.instrument_id))),
            revision=self.revision + 1,
            updated_at=fill.filled_at,
        )

    def _replace_position(self, position: PaperPosition) -> tuple[PaperPosition, ...]:
        remaining = tuple(
            item for item in self.positions if item.instrument_id != position.instrument_id
        )
        return tuple(
            sorted(remaining + (position,), key=lambda item: str(item.instrument_id))
        )


@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_id: PaperOrderId
    account_id: PaperAccountId
    instrument_id: InstrumentId
    side: PaperOrderSide
    quantity: Quantity
    reference_price: Price
    submitted_at: UtcInstant
    idempotency_key: str
    request_hash: str
    status: PaperOrderStatus = PaperOrderStatus.FILLED

    def __post_init__(self) -> None:
        key = self.idempotency_key.strip()
        request_hash = self.request_hash.strip().lower()
        if self.quantity.value <= 0:
            raise DomainValidationError("Paper order quantity must be positive")
        if not _IDEMPOTENCY_KEY.fullmatch(key):
            raise DomainValidationError("Paper order idempotency key is invalid")
        if len(request_hash) != 64 or any(char not in "0123456789abcdef" for char in request_hash):
            raise DomainValidationError("Paper order request hash must be SHA-256")
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(self, "request_hash", request_hash)


@dataclass(frozen=True, slots=True)
class PaperFill:
    fill_id: PaperFillId
    order_id: PaperOrderId
    account_id: PaperAccountId
    instrument_id: InstrumentId
    side: PaperOrderSide
    quantity: Quantity
    reference_price: Price
    execution_price: Price
    gross_notional: Money
    commission: Money
    filled_at: UtcInstant

    def __post_init__(self) -> None:
        currency = self.reference_price.currency
        if self.quantity.value <= 0:
            raise DomainValidationError("Paper fill quantity must be positive")
        if self.execution_price.currency != currency:
            raise DomainValidationError("Reference and execution currencies must match")
        if self.gross_notional.currency != currency or self.commission.currency != currency:
            raise DomainValidationError("Paper fill money must use the execution currency")
        expected = self.execution_price.amount * self.quantity.value
        if self.gross_notional.amount != expected or self.commission.amount < 0:
            raise DomainValidationError("Paper fill notional or commission is invalid")


@dataclass(frozen=True, slots=True)
class PaperTradeRequest:
    account_id: PaperAccountId
    instrument_id: InstrumentId
    side: PaperOrderSide
    quantity: Quantity
    reference_price: Price
    price_observed_at: UtcInstant
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.quantity.value <= 0:
            raise DomainValidationError("Paper trade quantity must be positive")
        if not _IDEMPOTENCY_KEY.fullmatch(self.idempotency_key.strip()):
            raise DomainValidationError("Paper trade idempotency key is invalid")
        object.__setattr__(self, "idempotency_key", self.idempotency_key.strip())

    @property
    def request_hash(self) -> str:
        payload = {
            "account_id": str(self.account_id),
            "instrument_id": str(self.instrument_id),
            "side": self.side.value,
            "quantity": str(self.quantity.value),
            "reference_price": str(self.reference_price.amount),
            "currency": str(self.reference_price.currency),
            "price_observed_at": self.price_observed_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class PaperExecution:
    account: PaperAccount
    order: PaperOrder
    fill: PaperFill

    def __post_init__(self) -> None:
        if self.order.order_id != self.fill.order_id:
            raise DomainValidationError("Paper execution order and fill do not match")
        if self.account.account_id != self.order.account_id:
            raise DomainValidationError("Paper execution account does not match")


def execution_price(
    reference: Price,
    side: PaperOrderSide,
    *,
    spread_bps: DecimalInput,
    slippage_bps: DecimalInput,
) -> Price:
    """Calculate a conservative deterministic paper execution price."""
    spread = to_decimal(spread_bps, field_name="spread bps")
    slippage = to_decimal(slippage_bps, field_name="slippage bps")
    if spread < 0 or slippage < 0:
        raise DomainValidationError("Paper execution costs cannot be negative")
    half_spread = spread / Decimal(20_000)
    slippage_rate = slippage / Decimal(10_000)
    direction = Decimal(1) if side is PaperOrderSide.BUY else Decimal(-1)
    multiplier = Decimal(1) + direction * (half_spread + slippage_rate)
    return Price(reference.amount * multiplier, reference.currency)
