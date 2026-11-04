"""Thread-safe append-only prediction ledger reference adapter."""

from __future__ import annotations

from datetime import date
from threading import RLock

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    ImmutableObjectConflictError,
)
from stock_predictor.domain.common.identifiers import (
    ModelVersionId,
    PredictionBatchId,
    PredictionId,
)
from stock_predictor.domain.mlops.inference import PredictionBatch, PredictionRecord


class InMemoryPredictionLedger:
    __slots__ = ("_batches", "_corrections", "_key_index", "_lock", "_predictions")

    def __init__(self) -> None:
        self._batches: dict[PredictionBatchId, PredictionBatch] = {}
        self._key_index: dict[str, PredictionBatchId] = {}
        self._predictions: dict[PredictionId, PredictionRecord] = {}
        self._corrections: dict[PredictionId, PredictionId] = {}
        self._lock = RLock()

    def append_batch(self, batch: PredictionBatch) -> None:
        with self._lock:
            existing_batch_id = self._key_index.get(batch.idempotency_key)
            if existing_batch_id is not None:
                existing = self._batches[existing_batch_id]
                if existing.fingerprint == batch.fingerprint:
                    return
                raise ImmutableObjectConflictError(
                    "Prediction idempotency key is already bound to another request"
                )
            if batch.batch_id in self._batches:
                raise DomainConflictError("Prediction batch ID is already present")
            if any(item.prediction_id in self._predictions for item in batch.predictions):
                raise DomainConflictError("Prediction ID is already present")
            self._batches[batch.batch_id] = batch
            self._key_index[batch.idempotency_key] = batch.batch_id
            self._predictions.update(
                {item.prediction_id: item for item in batch.predictions}
            )

    def get_batch_by_idempotency_key(self, key: str) -> PredictionBatch | None:
        normalized = key.strip()
        with self._lock:
            batch_id = self._key_index.get(normalized)
            return self._batches.get(batch_id) if batch_id is not None else None

    def get_prediction(self, prediction_id: PredictionId) -> PredictionRecord:
        with self._lock:
            try:
                return self._predictions[prediction_id]
            except KeyError as exc:
                raise DomainNotFoundError(
                    f"Prediction is not present: {prediction_id}"
                ) from exc

    def append_correction(
        self, original_prediction_id: PredictionId, correction: PredictionRecord
    ) -> None:
        with self._lock:
            original = self._predictions.get(original_prediction_id)
            if original is None:
                raise DomainNotFoundError(
                    f"Original prediction is not present: {original_prediction_id}"
                )
            if original_prediction_id in self._corrections:
                raise DomainConflictError("Prediction already has a direct correction")
            if correction.prediction_id in self._predictions:
                raise DomainConflictError("Correction prediction ID is already present")
            if correction.correction_of != original_prediction_id:
                raise DomainConflictError("Correction does not reference the original prediction")
            identity = (
                original.scope,
                original.instrument_id,
                original.as_of,
                original.horizon,
                original.model_version_id,
            )
            corrected_identity = (
                correction.scope,
                correction.instrument_id,
                correction.as_of,
                correction.horizon,
                correction.model_version_id,
            )
            if identity != corrected_identity:
                raise ImmutableObjectConflictError(
                    "Prediction correction changed immutable business identity"
                )
            self._predictions[correction.prediction_id] = correction
            self._corrections[original_prediction_id] = correction.prediction_id

    def list_predictions(
        self,
        *,
        model_version_id: ModelVersionId | None = None,
        target_key: str | None = None,
        as_of_from: date | None = None,
        as_of_to: date | None = None,
        latest_only: bool = True,
    ) -> tuple[PredictionRecord, ...]:
        target = target_key.strip().lower() if target_key is not None else None
        with self._lock:
            values = tuple(self._predictions.values())
            superseded = set(self._corrections) if latest_only else set()
        filtered = tuple(
            item
            for item in values
            if item.prediction_id not in superseded
            and (model_version_id is None or item.model_version_id == model_version_id)
            and (target is None or item.scope.target_key == target)
            and (as_of_from is None or item.as_of >= as_of_from)
            and (as_of_to is None or item.as_of <= as_of_to)
        )
        return tuple(sorted(filtered, key=lambda item: (item.as_of, str(item.prediction_id))))
