"""Thread-safe append-only realized-outcome repository."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    ImmutableObjectConflictError,
)
from stock_predictor.domain.common.identifiers import (
    ModelVersionId,
    OutcomeId,
    PredictionId,
)
from stock_predictor.domain.mlops.feedback import RealizedOutcome


class InMemoryOutcomeRepository:
    __slots__ = ("_history", "_lock", "_outcomes")

    def __init__(self) -> None:
        self._outcomes: dict[OutcomeId, RealizedOutcome] = {}
        self._history: dict[PredictionId, list[RealizedOutcome]] = {}
        self._lock = RLock()

    def append(self, outcome: RealizedOutcome) -> None:
        with self._lock:
            existing = self._outcomes.get(outcome.outcome_id)
            if existing is not None:
                if existing.fingerprint == outcome.fingerprint:
                    return
                raise ImmutableObjectConflictError("Outcome ID contains different content")
            history = self._history.setdefault(outcome.prediction_id, [])
            expected_revision = len(history) + 1
            expected_supersedes = history[-1].outcome_id if history else None
            if outcome.revision != expected_revision or outcome.supersedes != expected_supersedes:
                raise DomainConflictError("Outcome revision chain is inconsistent")
            if history:
                prior = history[-1]
                identity = (
                    prior.prediction_id,
                    prior.model_version_id,
                    prior.instrument_id,
                    prior.target_key,
                    prior.as_of,
                    prior.horizon_end,
                )
                current = (
                    outcome.prediction_id,
                    outcome.model_version_id,
                    outcome.instrument_id,
                    outcome.target_key,
                    outcome.as_of,
                    outcome.horizon_end,
                )
                if identity != current:
                    raise ImmutableObjectConflictError(
                        "Outcome revision changed immutable business identity"
                    )
            history.append(outcome)
            self._outcomes[outcome.outcome_id] = outcome

    def latest_for_prediction(
        self, prediction_id: PredictionId
    ) -> RealizedOutcome | None:
        with self._lock:
            history = self._history.get(prediction_id, [])
            return history[-1] if history else None

    def history(self, prediction_id: PredictionId) -> tuple[RealizedOutcome, ...]:
        with self._lock:
            return tuple(self._history.get(prediction_id, ()))

    def list_latest(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[RealizedOutcome, ...]:
        with self._lock:
            latest = tuple(history[-1] for history in self._history.values() if history)
        filtered = tuple(
            item
            for item in latest
            if model_version_id is None or item.model_version_id == model_version_id
        )
        return tuple(sorted(filtered, key=lambda item: (item.observed_at, str(item.outcome_id))))
