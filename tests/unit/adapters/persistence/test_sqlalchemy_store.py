from datetime import timedelta
from decimal import Decimal

import pytest

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
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.operations.paper import (
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperOrderSide,
)
from stock_predictor.domain.operations.records import (
    AuditEvent,
    AuditOutcome,
    IdempotencyRecord,
    IdempotencyStatus,
    JsonDocument,
    OutboxEvent,
)
from stock_predictor.domain.operations.slo import (
    HealthState,
    ServiceLevelObjective,
    SloIndicator,
    SloSnapshot,
)


def _audit(fixed_instant, sequence=1, previous_hash=None):
    return AuditEvent(
        AuditEventId.new(),
        sequence,
        fixed_instant,
        "operator",
        "paper.account.open",
        "paper.account",
        "account-1",
        AuditOutcome.SUCCESS,
        "correlation-1",
        "request-1",
        "test operation",
        JsonDocument.from_mapping({"test": True}),
        previous_hash,
    )


def _outbox(fixed_instant):
    return OutboxEvent(
        OutboxEventId.new(),
        "paper.account",
        "account-1",
        "paper.account.opened",
        1,
        fixed_instant,
        fixed_instant,
        JsonDocument.from_mapping({"account_id": "account-1"}),
        "correlation-1",
    )


def test_audit_repository_enforces_chain_and_rollback(operational_store, fixed_instant) -> None:
    first = _audit(fixed_instant)
    with operational_store() as uow:
        uow.audit.append(first)
        uow.commit()
    with operational_store() as uow:
        assert uow.audit.tail() == first
        assert uow.audit.list() == (first,)
        assert uow.audit.verify_chain()

    invalid = _audit(fixed_instant, 3, first.event_hash)
    with operational_store() as uow, pytest.raises(DomainConflictError):
        uow.audit.append(invalid)

    with operational_store() as uow:
        uow.audit.append(_audit(fixed_instant, 2, first.event_hash))
    with operational_store() as uow:
        assert len(uow.audit.list()) == 1


def test_audit_duplicate_and_list_bounds(operational_store, fixed_instant) -> None:
    event = _audit(fixed_instant)
    with operational_store() as uow:
        uow.audit.append(event)
        uow.commit()
    with operational_store() as uow:
        with pytest.raises((DomainConflictError, ImmutableObjectConflictError)):
            uow.audit.append(event)
        with pytest.raises(PersistenceError):
            uow.audit.list(limit=0)


def test_outbox_repository_updates_optimistically(operational_store, fixed_instant) -> None:
    event = _outbox(fixed_instant)
    with operational_store() as uow:
        uow.outbox.add(event)
        uow.commit()
    with operational_store() as uow:
        pending = uow.outbox.pending(limit=10, available_at=fixed_instant)
        assert pending == (event,)
        updated = event.published(fixed_instant.plus(timedelta(seconds=1)))
        uow.outbox.save(updated, expected_attempts=0)
        uow.commit()
    with operational_store() as uow:
        assert uow.outbox.get(event.event_id).status.value == "published"
        with pytest.raises(DomainConflictError):
            uow.outbox.save(updated, expected_attempts=0)
        with pytest.raises(DomainNotFoundError):
            uow.outbox.get(OutboxEventId.new())
        with pytest.raises(PersistenceError):
            uow.outbox.pending(limit=0, available_at=fixed_instant)


def test_idempotency_repository_is_compare_and_set(operational_store, fixed_instant) -> None:
    record = IdempotencyRecord(
        "request-key-0001",
        "operator",
        "paper.account.open",
        "a" * 64,
        IdempotencyStatus.PROCESSING,
        fixed_instant,
        fixed_instant.plus(timedelta(hours=1)),
    )
    with operational_store() as uow:
        uow.idempotency.add(record)
        uow.commit()
    completed = record.complete(
        response_status=201,
        response=JsonDocument.from_mapping({"account_id": "one"}),
    )
    with operational_store() as uow:
        uow.idempotency.save(completed, expected_revision=1)
        uow.commit()
    with operational_store() as uow:
        loaded = uow.idempotency.get(
            principal_id="operator",
            operation="paper.account.open",
            key="request-key-0001",
        )
        assert loaded == completed
        with pytest.raises(DomainConflictError):
            uow.idempotency.save(completed, expected_revision=1)


def _account(fixed_instant):
    return PaperAccount.open(
        account_id=PaperAccountId.new(),
        owner_subject="operator",
        name="Research Account",
        initial_cash="1000",
        currency=Currency("USD"),
        opened_at=fixed_instant,
    )


def _order_and_fill(account, fixed_instant):
    instrument_id = InstrumentId.new()
    order = PaperOrder(
        PaperOrderId.new(),
        account.account_id,
        instrument_id,
        PaperOrderSide.BUY,
        Quantity("1"),
        Price("100", Currency("USD")),
        fixed_instant,
        "paper-order-key-1",
        "b" * 64,
    )
    fill = PaperFill(
        PaperFillId.new(),
        order.order_id,
        account.account_id,
        instrument_id,
        PaperOrderSide.BUY,
        Quantity("1"),
        Price("100", Currency("USD")),
        Price("100", Currency("USD")),
        Money("100", Currency("USD")),
        Money("1", Currency("USD")),
        fixed_instant,
    )
    return order, fill


def test_paper_repository_persists_account_positions_orders_and_fills(
    operational_store,
    fixed_instant,
) -> None:
    account = _account(fixed_instant)
    order, fill = _order_and_fill(account, fixed_instant)
    updated = account.apply_fill(fill)
    with operational_store() as uow:
        uow.paper.add_account(account)
        uow.paper.save_account(updated, expected_revision=1)
        uow.paper.add_order(order)
        uow.paper.add_fill(fill)
        uow.commit()
    with operational_store() as uow:
        loaded = uow.paper.get_account(account.account_id)
        assert loaded == updated
        assert uow.paper.list_accounts(owner_subject="operator") == (updated,)
        assert uow.paper.get_order(order.order_id) == order
        assert uow.paper.list_orders(account.account_id) == (order,)
        assert uow.paper.list_fills(account.account_id) == (fill,)
        with pytest.raises(DomainConflictError):
            uow.paper.save_account(updated, expected_revision=1)
        with pytest.raises(DomainNotFoundError):
            uow.paper.get_account(PaperAccountId.new())


def test_slo_repository_round_trips_and_rejects_duplicate(
    operational_store,
    fixed_instant,
) -> None:
    objective = ServiceLevelObjective(
        "api.availability",
        SloIndicator.AVAILABILITY,
        "0.99",
        3600,
    )
    snapshot = SloSnapshot(
        SloSnapshotId.new(),
        objective,
        InstantInterval(fixed_instant, fixed_instant.plus(timedelta(minutes=30))),
        100,
        99,
        Decimal("0.99"),
        Decimal("0"),
        HealthState.HEALTHY,
        fixed_instant.plus(timedelta(hours=1)),
    )
    with operational_store() as uow:
        uow.slos.append(snapshot)
        uow.commit()
    with operational_store() as uow:
        assert uow.slos.latest("api.availability") == snapshot
        assert uow.slos.list(objective_name="api.availability") == (snapshot,)
        with pytest.raises(ImmutableObjectConflictError):
            uow.slos.append(snapshot)


def test_unit_of_work_requires_explicit_commit(operational_store, fixed_instant) -> None:
    with operational_store() as uow:
        uow.audit.append(_audit(fixed_instant))
    with operational_store() as uow:
        assert uow.audit.list() == ()
        uow.rollback()
        with pytest.raises(PersistenceError):
            uow.commit()


def test_store_health_check(operational_store) -> None:
    assert operational_store.health_check()
