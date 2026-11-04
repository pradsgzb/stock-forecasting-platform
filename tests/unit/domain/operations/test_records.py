from datetime import timedelta

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import AuditEventId, OutboxEventId
from stock_predictor.domain.operations.records import (
    AuditEvent,
    AuditOutcome,
    IdempotencyRecord,
    IdempotencyStatus,
    JsonDocument,
    OutboxEvent,
    OutboxStatus,
)


def test_json_document_is_canonical_and_hashed() -> None:
    left = JsonDocument.from_mapping({"b": 2, "a": [True, None]})
    right = JsonDocument('{"a":[true,null],"b":2}')

    assert left == right
    assert left.as_dict() == {"a": [True, None], "b": 2}
    assert len(left.sha256) == 64


@pytest.mark.parametrize("raw", ["[]", "not-json"])
def test_json_document_rejects_non_object_or_malformed_json(raw) -> None:
    with pytest.raises(DomainValidationError):
        JsonDocument(raw)


def _audit(fixed_instant, sequence=1, previous_hash=None):
    return AuditEvent(
        AuditEventId.new(),
        sequence,
        fixed_instant,
        "operator-1",
        "paper.order.execute",
        "paper.order",
        "order-1",
        AuditOutcome.SUCCESS,
        "correlation-1",
        "request-1",
        "authorized paper execution",
        JsonDocument.from_mapping({"quantity": "1"}),
        previous_hash,
    )


def test_audit_hash_chain_verifies(fixed_instant) -> None:
    first = _audit(fixed_instant)
    second = _audit(fixed_instant, 2, first.event_hash)

    assert first.verify(None)
    assert second.verify(first.event_hash)
    assert not second.verify("0" * 64)
    assert first.event_hash != second.event_hash


@pytest.mark.parametrize(
    ("sequence", "action", "previous"),
    [(0, "valid.name", None), (1, "!", None), (1, "valid.name", "bad")],
)
def test_audit_rejects_invalid_fields(fixed_instant, sequence, action, previous) -> None:
    with pytest.raises(DomainValidationError):
        AuditEvent(
            AuditEventId.new(),
            sequence,
            fixed_instant,
            "actor",
            action,
            "paper.order",
            "resource",
            AuditOutcome.SUCCESS,
            "correlation",
            "request-id",
            "reason",
            JsonDocument.from_mapping({}),
            previous,
        )


def _outbox(fixed_instant, **overrides):
    values = {
        "event_id": OutboxEventId.new(),
        "aggregate_type": "paper.order",
        "aggregate_id": "order-1",
        "event_type": "paper.order.filled",
        "event_version": 1,
        "occurred_at": fixed_instant,
        "available_at": fixed_instant,
        "payload": JsonDocument.from_mapping({"order_id": "order-1"}),
        "correlation_id": "correlation-1",
    }
    values.update(overrides)
    return OutboxEvent(**values)


def test_outbox_published_and_failure_transitions(fixed_instant) -> None:
    event = _outbox(fixed_instant)
    published = event.published(fixed_instant.plus(timedelta(seconds=1)))
    failed = event.failed("network unavailable", maximum_attempts=2)
    dead = failed.failed("still unavailable", maximum_attempts=2)

    assert published.status is OutboxStatus.PUBLISHED
    assert published.attempts == 1
    assert failed.status is OutboxStatus.PENDING
    assert dead.status is OutboxStatus.DEAD_LETTER
    assert event.fingerprint == published.fingerprint == dead.fingerprint


def test_outbox_rejects_invalid_state(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="Published"):
        _outbox(fixed_instant, status=OutboxStatus.PUBLISHED)
    with pytest.raises(DomainValidationError, match="Invalid outbox"):
        _outbox(fixed_instant).failed("", maximum_attempts=1)


def test_idempotency_record_completes_once(fixed_instant) -> None:
    record = IdempotencyRecord(
        "request-key-0001",
        "operator-1",
        "paper.order.execute",
        "a" * 64,
        IdempotencyStatus.PROCESSING,
        fixed_instant,
        fixed_instant.plus(timedelta(hours=1)),
    )
    completed = record.complete(
        response_status=201,
        response=JsonDocument.from_mapping({"order_id": "order-1"}),
    )

    assert completed.status is IdempotencyStatus.COMPLETED
    assert completed.revision == 2
    with pytest.raises(DomainValidationError, match="Only processing"):
        completed.complete(
            response_status=200,
            response=JsonDocument.from_mapping({}),
        )


def test_idempotency_record_rejects_invalid_identity(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="Idempotency key"):
        IdempotencyRecord(
            "bad",
            "operator",
            "paper.order.execute",
            "a" * 64,
            IdempotencyStatus.PROCESSING,
            fixed_instant,
            fixed_instant.plus(timedelta(hours=1)),
        )
