"""Transactional ports for operational persistence."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from stock_predictor.domain.common.identifiers import (
    OutboxEventId,
    PaperAccountId,
    PaperOrderId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.operations.paper import (
    PaperAccount,
    PaperFill,
    PaperOrder,
)
from stock_predictor.domain.operations.records import (
    AuditEvent,
    IdempotencyRecord,
    OutboxEvent,
)
from stock_predictor.domain.operations.slo import SloSnapshot


class AuditEventRepository(Protocol):
    def tail(self) -> AuditEvent | None:
        ...

    def append(self, event: AuditEvent) -> None:
        ...

    def list(self, *, limit: int = 100, after_sequence: int = 0) -> tuple[AuditEvent, ...]:
        ...

    def verify_chain(self) -> bool:
        ...


class OutboxRepository(Protocol):
    def add(self, event: OutboxEvent) -> None:
        ...

    def get(self, event_id: OutboxEventId) -> OutboxEvent:
        ...

    def pending(
        self,
        *,
        limit: int,
        available_at: UtcInstant,
    ) -> tuple[OutboxEvent, ...]:
        ...

    def save(self, event: OutboxEvent, *, expected_attempts: int) -> None:
        ...


class IdempotencyRepository(Protocol):
    def get(
        self,
        *,
        principal_id: str,
        operation: str,
        key: str,
    ) -> IdempotencyRecord | None:
        ...

    def add(self, record: IdempotencyRecord) -> None:
        ...

    def save(self, record: IdempotencyRecord, *, expected_revision: int) -> None:
        ...


class PaperTradingRepository(Protocol):
    def add_account(self, account: PaperAccount) -> None:
        ...

    def get_account(self, account_id: PaperAccountId) -> PaperAccount:
        ...

    def list_accounts(self, *, owner_subject: str | None = None) -> tuple[PaperAccount, ...]:
        ...

    def save_account(self, account: PaperAccount, *, expected_revision: int) -> None:
        ...

    def add_order(self, order: PaperOrder) -> None:
        ...

    def add_fill(self, fill: PaperFill) -> None:
        ...

    def get_order(self, order_id: PaperOrderId) -> PaperOrder:
        ...

    def list_orders(self, account_id: PaperAccountId) -> tuple[PaperOrder, ...]:
        ...

    def list_fills(self, account_id: PaperAccountId) -> tuple[PaperFill, ...]:
        ...


class SloSnapshotRepository(Protocol):
    def append(self, snapshot: SloSnapshot) -> None:
        ...

    def latest(self, objective_name: str) -> SloSnapshot | None:
        ...

    def list(self, *, objective_name: str | None = None) -> tuple[SloSnapshot, ...]:
        ...


@runtime_checkable
class OperationalUnitOfWork(Protocol):
    audit: AuditEventRepository
    outbox: OutboxRepository
    idempotency: IdempotencyRepository
    paper: PaperTradingRepository
    slos: SloSnapshotRepository

    def __enter__(self) -> Self:
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...


@runtime_checkable
class OperationalUnitOfWorkFactory(Protocol):
    def __call__(self) -> OperationalUnitOfWork:
        ...

    def health_check(self) -> bool:
        ...
