"""At-least-once transactional outbox dispatch with bounded retries."""

from __future__ import annotations

from dataclasses import dataclass

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.operations.records import OutboxStatus
from stock_predictor.ports.event_publisher import EventPublisher
from stock_predictor.ports.operational_store import OperationalUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class OutboxDispatchResult:
    selected: int
    published: int
    failed: int
    dead_lettered: int


class OutboxDispatcher:
    def __init__(
        self,
        store: OperationalUnitOfWorkFactory,
        publisher: EventPublisher,
        clock: Clock,
        *,
        maximum_attempts: int = 5,
    ) -> None:
        if maximum_attempts <= 0:
            raise ValueError("maximum_attempts must be positive")
        self._store = store
        self._publisher = publisher
        self._clock = clock
        self._maximum_attempts = maximum_attempts

    def dispatch(self, *, limit: int = 100) -> OutboxDispatchResult:
        with self._store() as uow:
            selected = uow.outbox.pending(
                limit=limit,
                available_at=self._clock.now(),
            )
        published = 0
        failed = 0
        dead_lettered = 0
        for candidate in selected:
            with self._store() as uow:
                current = uow.outbox.get(candidate.event_id)
                if current.status is not OutboxStatus.PENDING:
                    continue
                try:
                    self._publisher.publish(current)
                    updated = current.published(self._clock.now())
                    published += 1
                except Exception as exc:  # noqa: BLE001 - adapter failures become evidence.
                    updated = current.failed(
                        f"{type(exc).__name__}: {exc}",
                        maximum_attempts=self._maximum_attempts,
                    )
                    failed += 1
                    if updated.status is OutboxStatus.DEAD_LETTER:
                        dead_lettered += 1
                uow.outbox.save(updated, expected_attempts=current.attempts)
                uow.commit()
        return OutboxDispatchResult(len(selected), published, failed, dead_lettered)
