"""Port for immutable prediction batches and corrections."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import (
    ModelVersionId,
    PredictionId,
)
from stock_predictor.domain.mlops.inference import PredictionBatch, PredictionRecord


@runtime_checkable
class PredictionLedger(Protocol):
    def append_batch(self, batch: PredictionBatch) -> None:
        ...

    def get_batch_by_idempotency_key(self, key: str) -> PredictionBatch | None:
        ...

    def get_prediction(self, prediction_id: PredictionId) -> PredictionRecord:
        ...

    def append_correction(
        self, original_prediction_id: PredictionId, correction: PredictionRecord
    ) -> None:
        ...

    def list_predictions(
        self,
        *,
        model_version_id: ModelVersionId | None = None,
        target_key: str | None = None,
        as_of_from: date | None = None,
        as_of_to: date | None = None,
        latest_only: bool = True,
    ) -> tuple[PredictionRecord, ...]:
        ...
