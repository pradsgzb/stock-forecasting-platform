"""Batch-first model inference with immutable prediction-ledger publication."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import numpy as np

from stock_predictor.application.features.service import FeaturePipeline
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainError,
    DomainValidationError,
    InferenceError,
)
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    PredictionBatchId,
    PredictionId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import Probability
from stock_predictor.domain.market_data.features import FeatureSet, FeatureSnapshot
from stock_predictor.domain.mlops.inference import (
    PredictionBatch,
    PredictionBatchStatus,
    PredictionFailure,
    PredictionRecord,
)
from stock_predictor.domain.mlops.registry import (
    ModelDeploymentScope,
    ModelLifecycleState,
    RegisteredModelVersion,
    RegistryAlias,
)
from stock_predictor.domain.modeling.targets import TargetDefinition
from stock_predictor.ports.model_plugin import (
    FittedModel,
    FloatVector,
    ModelArtifactCodec,
)
from stock_predictor.ports.model_registry import ModelRegistryRepository
from stock_predictor.ports.prediction_ledger import PredictionLedger


@dataclass(frozen=True, slots=True)
class BatchInferenceRequest:
    scope: ModelDeploymentScope
    target: TargetDefinition
    feature_set: FeatureSet
    instrument_ids: tuple[InstrumentId, ...]
    as_of: date
    decision_cutoff: UtcInstant
    idempotency_key: str
    adjusted: bool = True
    fail_fast: bool = True
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        key = self.idempotency_key.strip()
        if not key or not self.instrument_ids:
            raise DomainValidationError("Inference request requires instruments and idempotency")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise DomainValidationError("Inference instruments must be unique")
        if self.scope.target_key != self.target.key:
            raise DomainValidationError("Inference target differs from deployment scope")
        object.__setattr__(self, "idempotency_key", key)
        payload = {
            "scope": self.scope.fingerprint,
            "target": self.target.fingerprint,
            "features": self.feature_set.fingerprint,
            "instruments": [str(item) for item in self.instrument_ids],
            "as_of": self.as_of.isoformat(),
            "decision_cutoff": self.decision_cutoff.isoformat(),
            "adjusted": self.adjusted,
            "fail_fast": self.fail_fast,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())


class ModelInferenceService:
    __slots__ = (
        "_allow_online",
        "_artifacts",
        "_clock",
        "_features",
        "_ledger",
        "_maximum_batch_size",
        "_registry",
    )

    def __init__(
        self,
        registry: ModelRegistryRepository,
        artifacts: ModelArtifactCodec,
        features: FeaturePipeline,
        ledger: PredictionLedger,
        clock: Clock,
        *,
        maximum_batch_size: int = 10_000,
        allow_online: bool = False,
    ) -> None:
        if maximum_batch_size <= 0:
            raise DomainValidationError("Maximum inference batch size must be positive")
        self._registry = registry
        self._artifacts = artifacts
        self._features = features
        self._ledger = ledger
        self._clock = clock
        self._maximum_batch_size = maximum_batch_size
        self._allow_online = allow_online

    def predict_batch(self, request: BatchInferenceRequest) -> PredictionBatch:
        existing = self._ledger.get_batch_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request.fingerprint:
                raise DomainConflictError(
                    "Inference idempotency key was reused for a different request"
                )
            return existing
        if len(request.instrument_ids) > self._maximum_batch_size:
            raise InferenceError("Inference request exceeds the maximum batch size")
        champion = self._registry.resolve_alias(request.scope, RegistryAlias.CHAMPION)
        if champion is None or champion.state is not ModelLifecycleState.CHAMPION:
            raise InferenceError("No deployable champion is assigned to the requested scope")
        if champion.artifact.signature.target_key != request.target.key:
            raise InferenceError("Champion target signature differs from inference target")
        expected_features = tuple(
            item.key for item in request.feature_set.definitions
        )
        if champion.artifact.signature.feature_keys != expected_features:
            raise InferenceError("Champion feature signature differs from inference feature set")
        model = self._artifacts.deserialize(champion.artifact)
        model.health_check()
        started_at = self._clock.now()
        batch_id = PredictionBatchId.new()
        snapshots: list[tuple[InstrumentId, FeatureSnapshot]] = []
        failures: list[PredictionFailure] = []
        for instrument_id in request.instrument_ids:
            try:
                snapshot = self._features.materialize(
                    request.feature_set,
                    instrument_id,
                    request.as_of,
                    request.decision_cutoff,
                    adjusted=request.adjusted,
                )
                if any(item.value is None for item in snapshot.observations):
                    raise InferenceError("Serving features contain unresolved missing values")
                snapshots.append((instrument_id, snapshot))
            except (DomainError, ValueError) as exc:
                failure = PredictionFailure(
                    instrument_id,
                    type(exc).__name__.lower(),
                    str(exc)[:500],
                )
                if request.fail_fast:
                    raise InferenceError(
                        f"Feature materialization failed for {instrument_id}: {exc}"
                    ) from exc
                failures.append(failure)
        predictions = self._predict(
            batch_id,
            request,
            champion,
            model,
            tuple(snapshots),
        )
        completed_at = self._clock.now()
        status = PredictionBatchStatus.COMPLETED
        if predictions and failures:
            status = PredictionBatchStatus.PARTIAL
        elif failures and not predictions:
            status = PredictionBatchStatus.FAILED
        batch = PredictionBatch(
            batch_id=batch_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.fingerprint,
            scope=request.scope,
            model_version_id=champion.model_version_id,
            target_definition_fingerprint=request.target.fingerprint,
            feature_set_fingerprint=request.feature_set.fingerprint,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            predictions=predictions,
            failures=tuple(failures),
        )
        self._ledger.append_batch(batch)
        return batch

    def predict_one(self, request: BatchInferenceRequest) -> PredictionRecord:
        if not self._allow_online:
            raise InferenceError("Online inference is disabled by policy")
        if len(request.instrument_ids) != 1:
            raise InferenceError("Online inference accepts exactly one instrument")
        batch = self.predict_batch(request)
        if len(batch.predictions) != 1:
            raise InferenceError("Online inference did not produce exactly one prediction")
        return batch.predictions[0]

    def _predict(
        self,
        batch_id: PredictionBatchId,
        request: BatchInferenceRequest,
        champion: RegisteredModelVersion,
        model: FittedModel,
        snapshots: tuple[tuple[InstrumentId, FeatureSnapshot], ...],
    ) -> tuple[PredictionRecord, ...]:
        if not snapshots:
            return ()
        matrix = np.asarray(
            [self._feature_row(snapshot) for _, snapshot in snapshots],
            dtype=np.float64,
        )
        if not np.isfinite(matrix).all():
            raise InferenceError("Inference feature matrix contains non-finite values")
        raw_predictions = model.predict(matrix)
        probabilities = model.predict_positive_probability(matrix)
        self._validate_outputs(len(snapshots), raw_predictions, probabilities)
        scores = probabilities if probabilities is not None else raw_predictions
        ranks = self._percentile_ranks(scores)
        generated_at = self._clock.now()
        result: list[PredictionRecord] = []
        for index, (instrument_id, snapshot) in enumerate(snapshots):
            probability = (
                Probability(Decimal(str(float(probabilities[index]))))
                if probabilities is not None
                else None
            )
            confidence = None
            if probability is not None:
                confidence = Probability(abs(probability.value - Decimal("0.5")) * 2)
            result.append(
                PredictionRecord(
                    prediction_id=PredictionId.new(),
                    batch_id=batch_id,
                    scope=request.scope,
                    instrument_id=instrument_id,
                    as_of=request.as_of,
                    decision_cutoff=request.decision_cutoff,
                    generated_at=generated_at,
                    horizon=request.target.horizon,
                    model_version_id=champion.model_version_id,
                    artifact_sha256=champion.artifact.payload_sha256,
                    signature_fingerprint=champion.artifact.signature.fingerprint,
                    feature_snapshot_id=snapshot.snapshot_id,
                    feature_snapshot_fingerprint=snapshot.fingerprint,
                    input_fingerprint=snapshot.input_fingerprint,
                    predicted_value=Decimal(str(float(raw_predictions[index]))),
                    positive_probability=probability,
                    cross_sectional_rank=Probability(Decimal(str(float(ranks[index])))),
                    confidence=confidence,
                )
            )
        return tuple(result)

    @staticmethod
    def _feature_row(snapshot: FeatureSnapshot) -> list[float]:
        row: list[float] = []
        for observation in snapshot.observations:
            if observation.value is None:
                raise InferenceError("Serving features contain unresolved missing values")
            row.append(float(observation.value))
        return row

    @staticmethod
    def _validate_outputs(
        count: int,
        predictions: FloatVector,
        probabilities: FloatVector | None,
    ) -> None:
        if predictions.ndim != 1 or len(predictions) != count:
            raise InferenceError("Model prediction output shape violates its contract")
        if not np.isfinite(predictions).all():
            raise InferenceError("Model produced non-finite predictions")
        if probabilities is None:
            return
        if probabilities.ndim != 1 or len(probabilities) != count:
            raise InferenceError("Model probability output shape violates its contract")
        if not np.isfinite(probabilities).all() or np.any(
            (probabilities < 0) | (probabilities > 1)
        ):
            raise InferenceError("Model produced invalid probabilities")

    @staticmethod
    def _percentile_ranks(values: FloatVector) -> FloatVector:
        count = len(values)
        if count == 1:
            return np.asarray([0.5], dtype=np.float64)
        order = np.argsort(values, kind="mergesort")
        ranks = np.empty(count, dtype=np.float64)
        position = 0
        while position < count:
            end = position + 1
            while end < count and math.isclose(
                float(values[order[end]]),
                float(values[order[position]]),
                rel_tol=0,
                abs_tol=1e-15,
            ):
                end += 1
            average = (position + end - 1) / 2
            for cursor in range(position, end):
                ranks[order[cursor]] = average / (count - 1)
            position = end
        return ranks
