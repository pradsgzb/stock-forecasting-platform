import pytest

from stock_predictor.adapters.events.in_memory_publisher import InMemoryEventPublisher
from stock_predictor.domain.common.identifiers import OutboxEventId
from stock_predictor.domain.operations.records import JsonDocument, OutboxEvent


def _event(fixed_instant) -> OutboxEvent:
    return OutboxEvent(
        event_id=OutboxEventId.new(),
        aggregate_type="paper.order",
        aggregate_id="order-1",
        event_type="paper.order.filled",
        event_version=1,
        occurred_at=fixed_instant,
        available_at=fixed_instant,
        payload=JsonDocument.from_mapping({"order_id": "order-1"}),
        correlation_id="correlation-1",
    )


def test_publisher_records_events_and_exposes_immutable_snapshot(fixed_instant) -> None:
    publisher = InMemoryEventPublisher()
    event = _event(fixed_instant)

    publisher.publish(event)

    assert publisher.events() == (event,)


def test_synthetic_failure_is_one_shot(fixed_instant) -> None:
    publisher = InMemoryEventPublisher()
    event = _event(fixed_instant)
    publisher.fail_next = True

    with pytest.raises(RuntimeError, match="synthetic"):
        publisher.publish(event)
    publisher.publish(event)

    assert publisher.events() == (event,)
