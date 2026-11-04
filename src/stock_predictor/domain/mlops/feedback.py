"""Realized outcomes and immutable feedback aggregates."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    LabelId,
    ModelVersionId,
    OutcomeId,
    PredictionId,
)
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.common.values import DecimalInput, Probability, to_decimal

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RealizedOutcome:
    """One revision of the realized outcome linked to an immutable prediction."""

    outcome_id: OutcomeId
    prediction_id: PredictionId
    model_version_id: ModelVersionId
    instrument_id: InstrumentId
    target_key: str
    as_of: date
    horizon_end: date
    observed_at: UtcInstant
    source_label_id: LabelId
    source_label_fingerprint: str
    prediction_value: Decimal
    actual_value: Decimal
    error: Decimal
    absolute_error: Decimal
    squared_error: Decimal
    positive_probability: Probability | None
    direction_correct: bool | None
    revision: int
    supersedes: OutcomeId | None = None
    fingerprint: str = field(init=False)

    def __init__(
        self,
        *,
        outcome_id: OutcomeId,
        prediction_id: PredictionId,
        model_version_id: ModelVersionId,
        instrument_id: InstrumentId,
        target_key: str,
        as_of: date,
        horizon_end: date,
        observed_at: UtcInstant,
        source_label_id: LabelId,
        source_label_fingerprint: str,
        prediction_value: DecimalInput,
        actual_value: DecimalInput,
        positive_probability: Probability | None,
        direction_correct: bool | None,
        revision: int,
        supersedes: OutcomeId | None = None,
    ) -> None:
        target = target_key.strip().lower()
        label_fingerprint = source_label_fingerprint.strip().lower()
        predicted = to_decimal(prediction_value, field_name="outcome prediction value")
        actual = to_decimal(actual_value, field_name="outcome actual value")
        error = predicted - actual
        if not target or not _SHA256.fullmatch(label_fingerprint):
            raise DomainValidationError("Outcome target and label fingerprint are required")
        if horizon_end <= as_of:
            raise DomainValidationError("Outcome horizon must end after prediction as-of date")
        if revision <= 0 or (revision == 1) is (supersedes is not None):
            raise DomainValidationError("Outcome revision and supersession are inconsistent")
        object.__setattr__(self, "outcome_id", outcome_id)
        object.__setattr__(self, "prediction_id", prediction_id)
        object.__setattr__(self, "model_version_id", model_version_id)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "target_key", target)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "horizon_end", horizon_end)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "source_label_id", source_label_id)
        object.__setattr__(self, "source_label_fingerprint", label_fingerprint)
        object.__setattr__(self, "prediction_value", predicted)
        object.__setattr__(self, "actual_value", actual)
        object.__setattr__(self, "error", error)
        object.__setattr__(self, "absolute_error", abs(error))
        object.__setattr__(self, "squared_error", error * error)
        object.__setattr__(self, "positive_probability", positive_probability)
        object.__setattr__(self, "direction_correct", direction_correct)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "supersedes", supersedes)
        payload = {
            "outcome": str(outcome_id),
            "prediction": str(prediction_id),
            "model": str(model_version_id),
            "instrument": str(instrument_id),
            "target": target,
            "as_of": as_of.isoformat(),
            "horizon_end": horizon_end.isoformat(),
            "observed_at": observed_at.isoformat(),
            "label": str(source_label_id),
            "label_fingerprint": label_fingerprint,
            "prediction_value": str(predicted),
            "actual_value": str(actual),
            "probability": str(positive_probability.value) if positive_probability else None,
            "direction_correct": direction_correct,
            "revision": revision,
            "supersedes": str(supersedes) if supersedes else None,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())


@dataclass(frozen=True, slots=True)
class OutcomeCollectionFailure:
    prediction_id: PredictionId
    reason: str

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            raise DomainValidationError("Outcome collection failure requires a reason")
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class OutcomeCollectionResult:
    collected: tuple[RealizedOutcome, ...]
    unchanged_prediction_ids: tuple[PredictionId, ...]
    failures: tuple[OutcomeCollectionFailure, ...]
    completed_at: UtcInstant


@dataclass(frozen=True, slots=True)
class FeedbackMetric:
    name: str
    value: Decimal

    def __init__(self, name: str, value: DecimalInput) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise DomainValidationError("Feedback metric name is required")
        object.__setattr__(self, "name", normalized)
        object.__setattr__(self, "value", to_decimal(value, field_name=normalized))


@dataclass(frozen=True, slots=True)
class FeedbackSummary:
    model_version_id: ModelVersionId
    target_key: str
    window: InstantInterval
    sample_count: int
    metrics: tuple[FeedbackMetric, ...]
    generated_at: UtcInstant
    outcome_fingerprints: tuple[str, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        target = self.target_key.strip().lower()
        names = tuple(item.name for item in self.metrics)
        fingerprints = tuple(item.strip().lower() for item in self.outcome_fingerprints)
        if not target or self.sample_count <= 0 or self.sample_count != len(fingerprints):
            raise DomainValidationError("Feedback summary sample count and lineage are invalid")
        if not self.metrics or len(set(names)) != len(names):
            raise DomainValidationError("Feedback summary requires unique metrics")
        if any(not _SHA256.fullmatch(item) for item in fingerprints):
            raise DomainValidationError("Feedback outcome fingerprints must be SHA-256")
        if self.generated_at < self.window.end:
            raise DomainValidationError("Feedback cannot be generated before its window ends")
        object.__setattr__(self, "target_key", target)
        object.__setattr__(self, "outcome_fingerprints", fingerprints)
        payload = {
            "model": str(self.model_version_id),
            "target": target,
            "window": (self.window.start.isoformat(), self.window.end.isoformat()),
            "samples": self.sample_count,
            "metrics": [(item.name, str(item.value)) for item in self.metrics],
            "outcomes": fingerprints,
            "generated_at": self.generated_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    def metric(self, name: str) -> FeedbackMetric:
        normalized = name.strip().lower()
        for metric in self.metrics:
            if metric.name == normalized:
                return metric
        raise DomainValidationError(f"Feedback metric is not present: {normalized}")
