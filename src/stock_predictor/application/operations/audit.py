"""Audit-event creation within an existing operational transaction."""

from __future__ import annotations

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.identifiers import AuditEventId
from stock_predictor.domain.operations.records import (
    AuditEvent,
    AuditOutcome,
    JsonDocument,
    JsonValue,
)
from stock_predictor.ports.operational_store import AuditEventRepository


class AuditEventFactory:
    """Extends the current tamper-evident audit chain deterministically."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def create(
        self,
        repository: AuditEventRepository,
        *,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: AuditOutcome,
        correlation_id: str,
        request_id: str,
        reason: str,
        attributes: dict[str, JsonValue],
    ) -> AuditEvent:
        tail = repository.tail()
        return AuditEvent(
            event_id=AuditEventId.new(),
            sequence=1 if tail is None else tail.sequence + 1,
            occurred_at=self._clock.now(),
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            correlation_id=correlation_id,
            request_id=request_id,
            reason=reason,
            attributes=JsonDocument.from_mapping(attributes),
            previous_hash=None if tail is None else tail.event_hash,
        )
