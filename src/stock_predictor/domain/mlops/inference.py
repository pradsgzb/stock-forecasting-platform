"""Immutable prediction batches and append-only prediction ledger records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    FeatureSnapshotId,
    InstrumentId,
    ModelVersionId,
    PredictionBatchId,
    PredictionId,
)
from stock_predictor.domain.common.temporal import PredictionHorizon, UtcInstant
from stock_predictor.domain.common.values import DecimalInput, Probability, to_decimal
from stock_predictor.domain.mlops.registry import ModelDeploymentScope

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PredictionBatchStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PredictionFailure:
    instrument_id: InstrumentId
    error_code: str
    message: str

    def __post_init__(self) -> None:
        code = self.error_code.strip().lower()
        message = self.message.strip()
        if not code or not message:
            raise DomainValidationError("Prediction failure requires code and message")
        object.__setattr__(self, "error_code", code)
        object.__setattr__(self, "message", message)


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    """Prediction frozen before the realized outcome is available."""

    prediction_id: PredictionId
    batch_id: PredictionBatchId
    scope: ModelDeploymentScope
    instrument_id: InstrumentId
    as_of: date
    decision_cutoff: UtcInstant
    generated_at: UtcInstant
    horizon: PredictionHorizon
    model_version_id: ModelVersionId
    artifact_sha256: str
    signature_fingerprint: str
    feature_snapshot_id: FeatureSnapshotId
    feature_snapshot_fingerprint: str
    input_fingerprint: str
    predicted_value: Decimal
    positive_probability: Probability | None = None
    interval_lower: Decimal | None = None
    interval_upper: Decimal | None = None
    expected_volatility: Decimal | None = None
    cross_sectional_rank: Probability | None = None
    confidence: Probability | None = None
    correction_of: PredictionId | None = None
    fingerprint: str = field(init=False)

    def __init__(
        self,
        *,
        prediction_id: PredictionId,
        batch_id: PredictionBatchId,
        scope: ModelDeploymentScope,
        instrument_id: InstrumentId,
        as_of: date,
        decision_cutoff: UtcInstant,
        generated_at: UtcInstant,
        horizon: PredictionHorizon,
        model_version_id: ModelVersionId,
        artifact_sha256: str,
        signature_fingerprint: str,
        feature_snapshot_id: FeatureSnapshotId,
        feature_snapshot_fingerprint: str,
        input_fingerprint: str,
        predicted_value: DecimalInput,
        positive_probability: Probability | None = None,
        interval_lower: DecimalInput | None = None,
        interval_upper: DecimalInput | None = None,
        expected_volatility: DecimalInput | None = None,
        cross_sectional_rank: Probability | None = None,
        confidence: Probability | None = None,
        correction_of: PredictionId | None = None,
    ) -> None:
        value = to_decimal(predicted_value, field_name="predicted value")
        lower = (
            to_decimal(interval_lower, field_name="prediction interval lower")
            if interval_lower is not None
            else None
        )
        upper = (
            to_decimal(interval_upper, field_name="prediction interval upper")
            if interval_upper is not None
            else None
        )
        volatility = (
            to_decimal(expected_volatility, field_name="expected volatility")
            if expected_volatility is not None
            else None
        )
        digests = (
            artifact_sha256.strip().lower(),
            signature_fingerprint.strip().lower(),
            feature_snapshot_fingerprint.strip().lower(),
            input_fingerprint.strip().lower(),
        )
        if any(not _SHA256.fullmatch(item) for item in digests):
            raise DomainValidationError("Prediction lineage fingerprints must be SHA-256")
        if generated_at < decision_cutoff:
            raise DomainValidationError("Prediction cannot be generated before decision cutoff")
        if (lower is None) is not (upper is None):
            raise DomainValidationError("Prediction interval requires both lower and upper bounds")
        if lower is not None and upper is not None and not lower <= value <= upper:
            raise DomainValidationError("Prediction value must fall within its interval")
        if volatility is not None and volatility < 0:
            raise DomainValidationError("Expected volatility cannot be negative")
        object.__setattr__(self, "prediction_id", prediction_id)
        object.__setattr__(self, "batch_id", batch_id)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "decision_cutoff", decision_cutoff)
        object.__setattr__(self, "generated_at", generated_at)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "model_version_id", model_version_id)
        object.__setattr__(self, "artifact_sha256", digests[0])
        object.__setattr__(self, "signature_fingerprint", digests[1])
        object.__setattr__(self, "feature_snapshot_id", feature_snapshot_id)
        object.__setattr__(self, "feature_snapshot_fingerprint", digests[2])
        object.__setattr__(self, "input_fingerprint", digests[3])
        object.__setattr__(self, "predicted_value", value)
        object.__setattr__(self, "positive_probability", positive_probability)
        object.__setattr__(self, "interval_lower", lower)
        object.__setattr__(self, "interval_upper", upper)
        object.__setattr__(self, "expected_volatility", volatility)
        object.__setattr__(self, "cross_sectional_rank", cross_sectional_rank)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "correction_of", correction_of)
        payload = {
            "prediction_id": str(prediction_id),
            "batch_id": str(batch_id),
            "scope": scope.fingerprint,
            "instrument": str(instrument_id),
            "as_of": as_of.isoformat(),
            "decision_cutoff": decision_cutoff.isoformat(),
            "generated_at": generated_at.isoformat(),
            "horizon": (horizon.amount, horizon.unit.value),
            "model": str(model_version_id),
            "artifact": digests[0],
            "signature": digests[1],
            "feature_snapshot": str(feature_snapshot_id),
            "feature_fingerprint": digests[2],
            "input_fingerprint": digests[3],
            "predicted_value": str(value),
            "positive_probability": (
                str(positive_probability.value) if positive_probability else None
            ),
            "interval": (
                (str(lower), str(upper)) if lower is not None and upper is not None else None
            ),
            "expected_volatility": str(volatility) if volatility is not None else None,
            "rank": str(cross_sectional_rank.value) if cross_sectional_rank else None,
            "confidence": str(confidence.value) if confidence else None,
            "correction_of": str(correction_of) if correction_of else None,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())


@dataclass(frozen=True, slots=True)
class PredictionBatch:
    batch_id: PredictionBatchId
    idempotency_key: str
    request_fingerprint: str
    scope: ModelDeploymentScope
    model_version_id: ModelVersionId
    target_definition_fingerprint: str
    feature_set_fingerprint: str
    started_at: UtcInstant
    completed_at: UtcInstant
    status: PredictionBatchStatus
    predictions: tuple[PredictionRecord, ...]
    failures: tuple[PredictionFailure, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        key = self.idempotency_key.strip()
        digests = (
            self.request_fingerprint.strip().lower(),
            self.target_definition_fingerprint.strip().lower(),
            self.feature_set_fingerprint.strip().lower(),
        )
        if not key or any(not _SHA256.fullmatch(item) for item in digests):
            raise DomainValidationError("Prediction batch requires idempotency and SHA-256 lineage")
        if self.completed_at < self.started_at:
            raise DomainValidationError("Prediction batch completion cannot precede start")
        if any(
            item.batch_id != self.batch_id
            or item.model_version_id != self.model_version_id
            or item.scope != self.scope
            for item in self.predictions
        ):
            raise DomainValidationError("Prediction batch contains inconsistent records")
        prediction_ids = tuple(item.prediction_id for item in self.predictions)
        failure_ids = tuple(item.instrument_id for item in self.failures)
        if len(set(prediction_ids)) != len(prediction_ids):
            raise DomainValidationError("Prediction IDs must be unique within a batch")
        if set(item.instrument_id for item in self.predictions) & set(failure_ids):
            raise DomainValidationError("An instrument cannot both succeed and fail in one batch")
        if self.status is PredictionBatchStatus.COMPLETED and (
            not self.predictions or self.failures
        ):
            raise DomainValidationError("Completed batches require predictions and no failures")
        if self.status is PredictionBatchStatus.PARTIAL and (
            not self.predictions or not self.failures
        ):
            raise DomainValidationError("Partial batches require predictions and failures")
        if self.status is PredictionBatchStatus.FAILED and (
            self.predictions or not self.failures
        ):
            raise DomainValidationError("Failed batches require failures and no predictions")
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(self, "request_fingerprint", digests[0])
        object.__setattr__(self, "target_definition_fingerprint", digests[1])
        object.__setattr__(self, "feature_set_fingerprint", digests[2])
        payload = {
            "batch": str(self.batch_id),
            "key": key,
            "request": digests[0],
            "scope": self.scope.fingerprint,
            "model": str(self.model_version_id),
            "target": digests[1],
            "features": digests[2],
            "started": self.started_at.isoformat(),
            "completed": self.completed_at.isoformat(),
            "status": self.status.value,
            "predictions": [item.fingerprint for item in self.predictions],
            "failures": [
                (str(item.instrument_id), item.error_code, item.message)
                for item in self.failures
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())
