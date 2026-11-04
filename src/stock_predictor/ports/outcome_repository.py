"""Port for append-only realized outcome revisions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import ModelVersionId, PredictionId
from stock_predictor.domain.mlops.feedback import RealizedOutcome


@runtime_checkable
class OutcomeRepository(Protocol):
    def append(self, outcome: RealizedOutcome) -> None:
        ...

    def latest_for_prediction(
        self, prediction_id: PredictionId
    ) -> RealizedOutcome | None:
        ...

    def history(self, prediction_id: PredictionId) -> tuple[RealizedOutcome, ...]:
        ...

    def list_latest(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[RealizedOutcome, ...]:
        ...
