"""Thread-safe append-only in-memory experiment event tracker."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.common.identifiers import ExperimentRunId
from stock_predictor.domain.modeling.experiments import ExperimentEvent


class InMemoryExperimentTracker:
    __slots__ = ("_events", "_lock")

    def __init__(self) -> None:
        self._events: dict[ExperimentRunId, list[ExperimentEvent]] = {}
        self._lock = RLock()

    def append(self, event: ExperimentEvent) -> None:
        with self._lock:
            events = self._events.setdefault(event.run_id, [])
            existing = next(
                (item for item in events if item.sequence == event.sequence),
                None,
            )
            if existing is not None:
                if existing.fingerprint == event.fingerprint:
                    return
                raise DomainConflictError(
                    f"Experiment sequence already contains different evidence: "
                    f"{event.run_id}/{event.sequence}"
                )
            expected = len(events) + 1
            if event.sequence != expected:
                raise DomainConflictError(
                    f"Experiment sequence must be contiguous; expected {expected}, "
                    f"received {event.sequence}"
                )
            events.append(event)

    def events(self, run_id: ExperimentRunId) -> tuple[ExperimentEvent, ...]:
        with self._lock:
            return tuple(self._events.get(run_id, ()))
