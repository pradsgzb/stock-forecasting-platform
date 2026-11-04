from stock_predictor.adapters.events.in_memory_publisher import InMemoryEventPublisher
from stock_predictor.application.operations.outbox import OutboxDispatcher
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.identifiers import OutboxEventId
from stock_predictor.domain.operations.records import (
    JsonDocument,
    OutboxEvent,
    OutboxStatus,
)


def _enqueue(store, instant) -> OutboxEvent:
    event = OutboxEvent(
        event_id=OutboxEventId.new(),
        aggregate_type="paper.order",
        aggregate_id="order-1",
        event_type="paper.order.filled",
        event_version=1,
        occurred_at=instant,
        available_at=instant,
        payload=JsonDocument.from_mapping({"order_id": "order-1"}),
        correlation_id="correlation-1",
    )
    with store() as uow:
        uow.outbox.add(event)
        uow.commit()
    return event


def test_dispatch_publishes_pending_event_once(operational_store, fixed_instant) -> None:
    event = _enqueue(operational_store, fixed_instant)
    publisher = InMemoryEventPublisher()
    dispatcher = OutboxDispatcher(
        operational_store,
        publisher,
        FixedClock(fixed_instant),
    )

    result = dispatcher.dispatch(limit=10)
    second = dispatcher.dispatch(limit=10)

    assert (result.selected, result.published, result.failed) == (1, 1, 0)
    assert second.selected == 0
    assert publisher.events() == (event,)
    with operational_store() as uow:
        assert uow.outbox.get(event.event_id).status is OutboxStatus.PUBLISHED


def test_dispatch_retries_and_dead_letters_bounded_failures(
    operational_store,
    fixed_instant,
) -> None:
    event = _enqueue(operational_store, fixed_instant)
    publisher = InMemoryEventPublisher()
    dispatcher = OutboxDispatcher(
        operational_store,
        publisher,
        FixedClock(fixed_instant),
        maximum_attempts=2,
    )

    publisher.fail_next = True
    first = dispatcher.dispatch()
    publisher.fail_next = True
    second = dispatcher.dispatch()

    assert first.failed == 1 and first.dead_lettered == 0
    assert second.failed == 1 and second.dead_lettered == 1
    with operational_store() as uow:
        persisted = uow.outbox.get(event.event_id)
    assert persisted.status is OutboxStatus.DEAD_LETTER
    assert persisted.attempts == 2
    assert "synthetic publisher failure" in (persisted.last_error or "")


def test_dispatcher_validates_limits(operational_store, fixed_instant) -> None:
    publisher = InMemoryEventPublisher()
    try:
        OutboxDispatcher(
            operational_store,
            publisher,
            FixedClock(fixed_instant),
            maximum_attempts=0,
        )
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected maximum-attempt validation")


def test_dispatch_does_not_publish_before_available_at(
    operational_store,
    fixed_instant,
) -> None:
    from datetime import timedelta

    event = OutboxEvent(
        event_id=OutboxEventId.new(),
        aggregate_type="paper.order",
        aggregate_id="order-delayed",
        event_type="paper.order.filled",
        event_version=1,
        occurred_at=fixed_instant,
        available_at=fixed_instant.plus(timedelta(minutes=5)),
        payload=JsonDocument.from_mapping({"order_id": "order-delayed"}),
        correlation_id="correlation-delayed",
    )
    with operational_store() as uow:
        uow.outbox.add(event)
        uow.commit()
    publisher = InMemoryEventPublisher()
    dispatcher = OutboxDispatcher(
        operational_store,
        publisher,
        FixedClock(fixed_instant),
    )

    result = dispatcher.dispatch()

    assert result.selected == 0
    assert publisher.events() == ()
