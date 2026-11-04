"""SQLAlchemy 2 operational store with explicit unit-of-work boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Final

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator, TypeEngine

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    ImmutableObjectConflictError,
    PersistenceError,
)
from stock_predictor.domain.common.identifiers import (
    AuditEventId,
    InstrumentId,
    OutboxEventId,
    PaperAccountId,
    PaperFillId,
    PaperOrderId,
    SloSnapshotId,
)
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.operations.paper import (
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperOrderSide,
    PaperOrderStatus,
    PaperPosition,
)
from stock_predictor.domain.operations.records import (
    AuditEvent,
    AuditOutcome,
    IdempotencyRecord,
    IdempotencyStatus,
    JsonDocument,
    OutboxEvent,
    OutboxStatus,
)
from stock_predictor.domain.operations.slo import (
    HealthState,
    ServiceLevelObjective,
    SloIndicator,
    SloSnapshot,
)
from stock_predictor.ports.operational_store import OperationalUnitOfWork


class ExactDecimal(TypeDecorator[Decimal]):
    """Preserve exact decimal values on SQLite and fixed precision elsewhere."""

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[object]:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(80))
        return dialect.type_descriptor(Numeric(38, 18))

    def process_bind_param(
        self,
        value: object,
        dialect: Dialect,
    ) -> Decimal | str | None:
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        return format(decimal_value, "f") if dialect.name == "sqlite" else decimal_value

    def process_result_value(
        self,
        value: object,
        dialect: Dialect,
    ) -> Decimal | None:
        del dialect
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))


_DECIMAL: Final[ExactDecimal] = ExactDecimal()


class Base(DeclarativeBase):
    """Operational metadata used by Alembic and local schema initialization."""


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_audit_sequence_positive"),
        UniqueConstraint("sequence", name="uq_audit_sequence"),
        UniqueConstraint("event_hash", name="uq_audit_hash"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attributes_json: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("event_version > 0", name="ck_outbox_version_positive"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
        Index("ix_outbox_pending", "status", "available_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "principal_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_identity",
        ),
        CheckConstraint("revision > 0", name="ck_idempotency_revision_positive"),
        Index("ix_idempotency_expiry", "expires_at"),
    )

    principal_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    operation: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[str | None] = mapped_column(Text)


class PaperAccountRow(Base):
    __tablename__ = "paper_accounts"
    __table_args__ = (
        CheckConstraint("cash_amount >= 0", name="ck_paper_cash_nonnegative"),
        CheckConstraint("revision > 0", name="ck_paper_revision_positive"),
        Index("ix_paper_accounts_owner", "owner_subject"),
    )

    account_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cash_amount: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    realized_pnl_amount: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperPositionRow(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_paper_position_quantity_positive"),
    )

    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("paper_accounts.account_id", ondelete="CASCADE"),
        primary_key=True,
    )
    instrument_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    average_price: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class PaperOrderRow(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "idempotency_key",
            name="uq_paper_order_idempotency",
        ),
        Index("ix_paper_orders_account_submitted", "account_id", "submitted_at"),
    )

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("paper_accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(String(36), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class PaperFillRow(Base):
    __tablename__ = "paper_fills"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_paper_fill_order"),
    )

    fill_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("paper_orders.order_id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(36), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    execution_price: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    gross_notional: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    commission: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SloSnapshotRow(Base):
    __tablename__ = "slo_snapshots"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_slo_fingerprint"),
        Index("ix_slo_objective_created", "objective_name", "created_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    objective_name: Mapped[str] = mapped_column(String(128), nullable=False)
    indicator: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_threshold_ms: Mapped[Decimal | None] = mapped_column(_DECIMAL)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_events: Mapped[int] = mapped_column(BigInteger, nullable=False)
    good_events: Mapped[int] = mapped_column(BigInteger, nullable=False)
    measured_value: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    error_budget_remaining: Mapped[Decimal] = mapped_column(_DECIMAL, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


def _instant(value: datetime) -> UtcInstant:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return UtcInstant(aware)


class SqlAlchemyAuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def tail(self) -> AuditEvent | None:
        row = self._session.scalar(
            select(AuditEventRow).order_by(AuditEventRow.sequence.desc()).limit(1)
        )
        return _audit_from_row(row) if row is not None else None

    def append(self, event: AuditEvent) -> None:
        tail = self.tail()
        expected_sequence = 1 if tail is None else tail.sequence + 1
        expected_hash = None if tail is None else tail.event_hash
        if event.sequence != expected_sequence or not event.verify(expected_hash):
            raise DomainConflictError("Audit event does not extend the current hash chain")
        self._session.add(_audit_to_row(event))
        self._flush("Audit event conflicts with existing immutable evidence")

    def list(self, *, limit: int = 100, after_sequence: int = 0) -> tuple[AuditEvent, ...]:
        if not 1 <= limit <= 1000 or after_sequence < 0:
            raise PersistenceError("Audit list bounds are invalid")
        rows = self._session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.sequence > after_sequence)
            .order_by(AuditEventRow.sequence)
            .limit(limit)
        ).all()
        return tuple(_audit_from_row(row) for row in rows)

    def verify_chain(self) -> bool:
        rows = self._session.scalars(
            select(AuditEventRow).order_by(AuditEventRow.sequence)
        ).all()
        previous: str | None = None
        sequence = 1
        for row in rows:
            event = _audit_from_row(row)
            if event.sequence != sequence or not event.verify(previous):
                return False
            previous = event.event_hash
            sequence += 1
        return True

    def _flush(self, message: str) -> None:
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise ImmutableObjectConflictError(message) from exc


class SqlAlchemyOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: OutboxEvent) -> None:
        self._session.add(_outbox_to_row(event))
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise ImmutableObjectConflictError("Outbox event already exists") from exc

    def get(self, event_id: OutboxEventId) -> OutboxEvent:
        row = self._session.get(OutboxEventRow, str(event_id))
        if row is None:
            raise DomainNotFoundError(f"Outbox event not found: {event_id}")
        return _outbox_from_row(row)

    def pending(
        self,
        *,
        limit: int,
        available_at: UtcInstant,
    ) -> tuple[OutboxEvent, ...]:
        if not 1 <= limit <= 1000:
            raise PersistenceError("Outbox batch size must be between 1 and 1000")
        rows = self._session.scalars(
            select(OutboxEventRow)
            .where(
                OutboxEventRow.status == OutboxStatus.PENDING.value,
                OutboxEventRow.available_at <= available_at.value,
            )
            .order_by(OutboxEventRow.available_at, OutboxEventRow.event_id)
            .limit(limit)
        ).all()
        return tuple(_outbox_from_row(row) for row in rows)

    def save(self, event: OutboxEvent, *, expected_attempts: int) -> None:
        statement = (
            update(OutboxEventRow)
            .where(
                OutboxEventRow.event_id == str(event.event_id),
                OutboxEventRow.attempts == expected_attempts,
                OutboxEventRow.fingerprint == event.fingerprint,
            )
            .values(
                status=event.status.value,
                attempts=event.attempts,
                published_at=(
                    event.published_at.value if event.published_at is not None else None
                ),
                last_error=event.last_error,
            )
        )
        result = self._session.execute(statement)
        if result.rowcount != 1:
            raise DomainConflictError("Outbox event changed concurrently or payload changed")


class SqlAlchemyIdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(
        self,
        *,
        principal_id: str,
        operation: str,
        key: str,
    ) -> IdempotencyRecord | None:
        row = self._session.get(IdempotencyRow, (principal_id, operation, key))
        return _idempotency_from_row(row) if row is not None else None

    def add(self, record: IdempotencyRecord) -> None:
        self._session.add(_idempotency_to_row(record))
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise DomainConflictError("Idempotency key already exists") from exc

    def save(self, record: IdempotencyRecord, *, expected_revision: int) -> None:
        result = self._session.execute(
            update(IdempotencyRow)
            .where(
                IdempotencyRow.principal_id == record.principal_id,
                IdempotencyRow.operation == record.operation,
                IdempotencyRow.idempotency_key == record.key,
                IdempotencyRow.revision == expected_revision,
                IdempotencyRow.request_hash == record.request_hash,
            )
            .values(
                status=record.status.value,
                revision=record.revision,
                response_status=record.response_status,
                response_json=(record.response.canonical if record.response else None),
            )
        )
        if result.rowcount != 1:
            raise DomainConflictError("Idempotency record changed concurrently")


class SqlAlchemyPaperTradingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_account(self, account: PaperAccount) -> None:
        self._session.add(_account_to_row(account))
        self._session.add_all(_position_rows(account))
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise DomainConflictError("Paper account already exists") from exc

    def get_account(self, account_id: PaperAccountId) -> PaperAccount:
        row = self._session.get(PaperAccountRow, str(account_id))
        if row is None:
            raise DomainNotFoundError(f"Paper account not found: {account_id}")
        positions = self._session.scalars(
            select(PaperPositionRow).where(
                PaperPositionRow.account_id == str(account_id)
            )
        ).all()
        return _account_from_rows(row, positions)

    def list_accounts(self, *, owner_subject: str | None = None) -> tuple[PaperAccount, ...]:
        statement = select(PaperAccountRow).order_by(PaperAccountRow.created_at)
        if owner_subject is not None:
            statement = statement.where(PaperAccountRow.owner_subject == owner_subject)
        rows = self._session.scalars(statement).all()
        return tuple(self.get_account(PaperAccountId.parse(row.account_id)) for row in rows)

    def save_account(self, account: PaperAccount, *, expected_revision: int) -> None:
        result = self._session.execute(
            update(PaperAccountRow)
            .where(
                PaperAccountRow.account_id == str(account.account_id),
                PaperAccountRow.revision == expected_revision,
            )
            .values(
                cash_amount=account.cash.amount,
                realized_pnl_amount=account.realized_pnl.amount,
                revision=account.revision,
                updated_at=account.updated_at.value,
            )
        )
        if result.rowcount != 1:
            raise DomainConflictError("Paper account changed concurrently")
        self._session.execute(
            delete(PaperPositionRow).where(
                PaperPositionRow.account_id == str(account.account_id)
            )
        )
        self._session.add_all(_position_rows(account))
        self._session.flush()

    def add_order(self, order: PaperOrder) -> None:
        self._session.add(_order_to_row(order))
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise DomainConflictError("Paper order identity or idempotency key exists") from exc

    def add_fill(self, fill: PaperFill) -> None:
        self._session.add(_fill_to_row(fill))
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise DomainConflictError("Paper fill already exists for this order") from exc

    def get_order(self, order_id: PaperOrderId) -> PaperOrder:
        row = self._session.get(PaperOrderRow, str(order_id))
        if row is None:
            raise DomainNotFoundError(f"Paper order not found: {order_id}")
        return _order_from_row(row)

    def list_orders(self, account_id: PaperAccountId) -> tuple[PaperOrder, ...]:
        rows = self._session.scalars(
            select(PaperOrderRow)
            .where(PaperOrderRow.account_id == str(account_id))
            .order_by(PaperOrderRow.submitted_at, PaperOrderRow.order_id)
        ).all()
        return tuple(_order_from_row(row) for row in rows)

    def list_fills(self, account_id: PaperAccountId) -> tuple[PaperFill, ...]:
        rows = self._session.scalars(
            select(PaperFillRow)
            .where(PaperFillRow.account_id == str(account_id))
            .order_by(PaperFillRow.filled_at, PaperFillRow.fill_id)
        ).all()
        return tuple(_fill_from_row(row) for row in rows)


class SqlAlchemySloSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, snapshot: SloSnapshot) -> None:
        self._session.add(_slo_to_row(snapshot))
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise ImmutableObjectConflictError("SLO snapshot already exists") from exc

    def latest(self, objective_name: str) -> SloSnapshot | None:
        row = self._session.scalar(
            select(SloSnapshotRow)
            .where(SloSnapshotRow.objective_name == objective_name.strip().lower())
            .order_by(SloSnapshotRow.created_at.desc())
            .limit(1)
        )
        return _slo_from_row(row) if row is not None else None

    def list(self, *, objective_name: str | None = None) -> tuple[SloSnapshot, ...]:
        statement = select(SloSnapshotRow).order_by(SloSnapshotRow.created_at)
        if objective_name is not None:
            statement = statement.where(
                SloSnapshotRow.objective_name == objective_name.strip().lower()
            )
        return tuple(_slo_from_row(row) for row in self._session.scalars(statement).all())


class SqlAlchemyOperationalUnitOfWork(OperationalUnitOfWork):
    """One explicit database transaction with repositories sharing a session."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session = session_factory()
        self.audit = SqlAlchemyAuditRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self._session)
        self.paper = SqlAlchemyPaperTradingRepository(self._session)
        self.slos = SqlAlchemySloSnapshotRepository(self._session)
        self._completed = False

    def __enter__(self) -> SqlAlchemyOperationalUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        del exc_value, traceback
        try:
            if exc_type is not None or not self._completed:
                self._session.rollback()
        finally:
            self._session.close()
        return None

    def commit(self) -> None:
        if self._completed:
            raise PersistenceError("Operational unit of work is already completed")
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise DomainConflictError("Operational transaction violated a constraint") from exc
        self._completed = True

    def rollback(self) -> None:
        if not self._completed:
            self._session.rollback()
            self._completed = True


class SqlAlchemyOperationalStore:
    """Unit-of-work factory for SQLite locally and PostgreSQL in managed deployments."""

    def __init__(
        self,
        database_url: str,
        *,
        echo: bool = False,
        pool_pre_ping: bool = True,
    ) -> None:
        if not database_url.strip():
            raise PersistenceError("Database URL cannot be blank")
        connect_args: dict[str, object] = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self.engine = create_engine(
            database_url,
            echo=echo,
            pool_pre_ping=pool_pre_ping,
            connect_args=connect_args,
        )
        self._session_factory = sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    def __call__(self) -> SqlAlchemyOperationalUnitOfWork:
        return SqlAlchemyOperationalUnitOfWork(self._session_factory)

    def health_check(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return connection.scalar(text("SELECT 1")) == 1
        except Exception:  # noqa: BLE001 - health boundary converts driver failures to false.
            return False

    def create_schema_for_testing(self) -> None:
        """Create tables only for tests/local demos; production uses Alembic migrations."""
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


def _audit_to_row(event: AuditEvent) -> AuditEventRow:
    return AuditEventRow(
        event_id=str(event.event_id),
        sequence=event.sequence,
        occurred_at=event.occurred_at.value,
        actor_id=event.actor_id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        outcome=event.outcome.value,
        correlation_id=event.correlation_id,
        request_id=event.request_id,
        reason=event.reason,
        attributes_json=event.attributes.canonical,
        previous_hash=event.previous_hash,
        event_hash=event.event_hash,
    )


def _audit_from_row(row: AuditEventRow) -> AuditEvent:
    event = AuditEvent(
        event_id=AuditEventId.parse(row.event_id),
        sequence=row.sequence,
        occurred_at=_instant(row.occurred_at),
        actor_id=row.actor_id,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        outcome=AuditOutcome(row.outcome),
        correlation_id=row.correlation_id,
        request_id=row.request_id,
        reason=row.reason,
        attributes=JsonDocument(row.attributes_json),
        previous_hash=row.previous_hash,
    )
    if event.event_hash != row.event_hash:
        raise PersistenceError("Stored audit event hash does not match its content")
    return event


def _outbox_to_row(event: OutboxEvent) -> OutboxEventRow:
    return OutboxEventRow(
        event_id=str(event.event_id),
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        event_version=event.event_version,
        occurred_at=event.occurred_at.value,
        available_at=event.available_at.value,
        payload_json=event.payload.canonical,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        status=event.status.value,
        attempts=event.attempts,
        published_at=event.published_at.value if event.published_at else None,
        last_error=event.last_error,
        fingerprint=event.fingerprint,
    )


def _outbox_from_row(row: OutboxEventRow) -> OutboxEvent:
    event = OutboxEvent(
        event_id=OutboxEventId.parse(row.event_id),
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        event_version=row.event_version,
        occurred_at=_instant(row.occurred_at),
        available_at=_instant(row.available_at),
        payload=JsonDocument(row.payload_json),
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        status=OutboxStatus(row.status),
        attempts=row.attempts,
        published_at=_instant(row.published_at) if row.published_at else None,
        last_error=row.last_error,
    )
    if event.fingerprint != row.fingerprint:
        raise PersistenceError("Stored outbox payload fingerprint does not match")
    return event


def _idempotency_to_row(record: IdempotencyRecord) -> IdempotencyRow:
    return IdempotencyRow(
        principal_id=record.principal_id,
        operation=record.operation,
        idempotency_key=record.key,
        request_hash=record.request_hash,
        status=record.status.value,
        created_at=record.created_at.value,
        expires_at=record.expires_at.value,
        revision=record.revision,
        response_status=record.response_status,
        response_json=record.response.canonical if record.response else None,
    )


def _idempotency_from_row(row: IdempotencyRow) -> IdempotencyRecord:
    return IdempotencyRecord(
        key=row.idempotency_key,
        principal_id=row.principal_id,
        operation=row.operation,
        request_hash=row.request_hash,
        status=IdempotencyStatus(row.status),
        created_at=_instant(row.created_at),
        expires_at=_instant(row.expires_at),
        revision=row.revision,
        response_status=row.response_status,
        response=JsonDocument(row.response_json) if row.response_json else None,
    )


def _account_to_row(account: PaperAccount) -> PaperAccountRow:
    return PaperAccountRow(
        account_id=str(account.account_id),
        owner_subject=account.owner_subject,
        name=account.name,
        currency=str(account.base_currency),
        cash_amount=account.cash.amount,
        realized_pnl_amount=account.realized_pnl.amount,
        revision=account.revision,
        created_at=account.created_at.value,
        updated_at=account.updated_at.value,
    )


def _position_rows(account: PaperAccount) -> list[PaperPositionRow]:
    return [
        PaperPositionRow(
            account_id=str(account.account_id),
            instrument_id=str(item.instrument_id),
            quantity=item.quantity.value,
            average_price=item.average_price.amount,
            currency=str(item.average_price.currency),
        )
        for item in account.positions
    ]


def _account_from_rows(
    row: PaperAccountRow,
    positions: list[PaperPositionRow],
) -> PaperAccount:
    currency = Currency(row.currency)
    return PaperAccount(
        account_id=PaperAccountId.parse(row.account_id),
        owner_subject=row.owner_subject,
        name=row.name,
        base_currency=currency,
        cash=Money(row.cash_amount, currency),
        realized_pnl=Money(row.realized_pnl_amount, currency),
        positions=tuple(
            PaperPosition(
                InstrumentId.parse(item.instrument_id),
                Quantity(item.quantity),
                Price(item.average_price, Currency(item.currency)),
            )
            for item in positions
        ),
        revision=row.revision,
        created_at=_instant(row.created_at),
        updated_at=_instant(row.updated_at),
    )


def _order_to_row(order: PaperOrder) -> PaperOrderRow:
    return PaperOrderRow(
        order_id=str(order.order_id),
        account_id=str(order.account_id),
        instrument_id=str(order.instrument_id),
        side=order.side.value,
        quantity=order.quantity.value,
        reference_price=order.reference_price.amount,
        currency=str(order.reference_price.currency),
        submitted_at=order.submitted_at.value,
        idempotency_key=order.idempotency_key,
        request_hash=order.request_hash,
        status=order.status.value,
    )


def _order_from_row(row: PaperOrderRow) -> PaperOrder:
    return PaperOrder(
        order_id=PaperOrderId.parse(row.order_id),
        account_id=PaperAccountId.parse(row.account_id),
        instrument_id=InstrumentId.parse(row.instrument_id),
        side=PaperOrderSide(row.side),
        quantity=Quantity(row.quantity),
        reference_price=Price(row.reference_price, Currency(row.currency)),
        submitted_at=_instant(row.submitted_at),
        idempotency_key=row.idempotency_key,
        request_hash=row.request_hash,
        status=PaperOrderStatus(row.status),
    )


def _fill_to_row(fill: PaperFill) -> PaperFillRow:
    return PaperFillRow(
        fill_id=str(fill.fill_id),
        order_id=str(fill.order_id),
        account_id=str(fill.account_id),
        instrument_id=str(fill.instrument_id),
        side=fill.side.value,
        quantity=fill.quantity.value,
        reference_price=fill.reference_price.amount,
        execution_price=fill.execution_price.amount,
        gross_notional=fill.gross_notional.amount,
        commission=fill.commission.amount,
        currency=str(fill.execution_price.currency),
        filled_at=fill.filled_at.value,
    )


def _fill_from_row(row: PaperFillRow) -> PaperFill:
    currency = Currency(row.currency)
    return PaperFill(
        fill_id=PaperFillId.parse(row.fill_id),
        order_id=PaperOrderId.parse(row.order_id),
        account_id=PaperAccountId.parse(row.account_id),
        instrument_id=InstrumentId.parse(row.instrument_id),
        side=PaperOrderSide(row.side),
        quantity=Quantity(row.quantity),
        reference_price=Price(row.reference_price, currency),
        execution_price=Price(row.execution_price, currency),
        gross_notional=Money(row.gross_notional, currency),
        commission=Money(row.commission, currency),
        filled_at=_instant(row.filled_at),
    )


def _slo_to_row(snapshot: SloSnapshot) -> SloSnapshotRow:
    objective = snapshot.objective
    return SloSnapshotRow(
        snapshot_id=str(snapshot.snapshot_id),
        objective_name=objective.name,
        indicator=objective.indicator.value,
        target=objective.target,
        window_seconds=objective.window_seconds,
        latency_threshold_ms=objective.latency_threshold_milliseconds,
        window_start=snapshot.window.start.value,
        window_end=snapshot.window.end.value,
        total_events=snapshot.total_events,
        good_events=snapshot.good_events,
        measured_value=snapshot.measured_value,
        error_budget_remaining=snapshot.error_budget_remaining,
        state=snapshot.state.value,
        created_at=snapshot.created_at.value,
        fingerprint=snapshot.fingerprint,
    )


def _slo_from_row(row: SloSnapshotRow) -> SloSnapshot:
    objective = ServiceLevelObjective(
        row.objective_name,
        SloIndicator(row.indicator),
        row.target,
        row.window_seconds,
        row.latency_threshold_ms,
    )
    snapshot = SloSnapshot(
        snapshot_id=SloSnapshotId.parse(row.snapshot_id),
        objective=objective,
        window=InstantInterval(_instant(row.window_start), _instant(row.window_end)),
        total_events=row.total_events,
        good_events=row.good_events,
        measured_value=row.measured_value,
        error_budget_remaining=row.error_budget_remaining,
        state=HealthState(row.state),
        created_at=_instant(row.created_at),
    )
    if snapshot.fingerprint != row.fingerprint:
        raise PersistenceError("Stored SLO snapshot fingerprint does not match")
    return snapshot


__all__ = [
    "Base",
    "SqlAlchemyOperationalStore",
    "SqlAlchemyOperationalUnitOfWork",
]
