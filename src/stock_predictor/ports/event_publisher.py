"""External event publication port for transactional outbox dispatch."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.operations.records import OutboxEvent


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, event: OutboxEvent) -> None:
        ...
