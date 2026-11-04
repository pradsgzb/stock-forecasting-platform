"""Thread-safe publisher used for contract tests and local demonstrations."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.operations.records import OutboxEvent


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self._events: list[OutboxEvent] = []
        self._lock = RLock()
        self.fail_next = False

    def publish(self, event: OutboxEvent) -> None:
        with self._lock:
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("synthetic publisher failure")
            self._events.append(event)

    def events(self) -> tuple[OutboxEvent, ...]:
        with self._lock:
            return tuple(self._events)
