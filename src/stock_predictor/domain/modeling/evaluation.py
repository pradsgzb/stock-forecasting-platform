"""Framework-independent model-evaluation evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal
from stock_predictor.domain.modeling.models import LearningTask


class MetricDirection(StrEnum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


@dataclass(frozen=True, slots=True)
class MetricValue:
    name: str
    value: Decimal
    direction: MetricDirection

    def __init__(
        self,
        name: str,
        value: DecimalInput,
        direction: MetricDirection,
    ) -> None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise DomainValidationError("Metric name is required")
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "value", to_decimal(value, field_name=normalized_name))
        object.__setattr__(self, "direction", direction)

    def better_than(self, other: MetricValue) -> bool:
        if self.name != other.name or self.direction is not other.direction:
            raise DomainValidationError("Only matching metrics can be compared")
        if self.direction is MetricDirection.MINIMIZE:
            return self.value < other.value
        return self.value > other.value


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower_bound: Decimal
    upper_bound: Decimal
    sample_count: int
    mean_predicted_probability: Decimal
    observed_positive_rate: Decimal

    def __init__(
        self,
        lower_bound: DecimalInput,
        upper_bound: DecimalInput,
        sample_count: int,
        mean_predicted_probability: DecimalInput,
        observed_positive_rate: DecimalInput,
    ) -> None:
        lower = to_decimal(lower_bound, field_name="calibration lower bound")
        upper = to_decimal(upper_bound, field_name="calibration upper bound")
        predicted = to_decimal(
            mean_predicted_probability,
            field_name="mean predicted probability",
        )
        observed = to_decimal(observed_positive_rate, field_name="observed positive rate")
        if not Decimal(0) <= lower < upper <= Decimal(1):
            raise DomainValidationError("Calibration bounds must partition [0, 1]")
        if sample_count <= 0:
            raise DomainValidationError("Calibration bins cannot be empty")
        if not Decimal(0) <= predicted <= Decimal(1):
            raise DomainValidationError("Predicted probability must be within [0, 1]")
        if not Decimal(0) <= observed <= Decimal(1):
            raise DomainValidationError("Observed rate must be within [0, 1]")
        object.__setattr__(self, "lower_bound", lower)
        object.__setattr__(self, "upper_bound", upper)
        object.__setattr__(self, "sample_count", sample_count)
        object.__setattr__(self, "mean_predicted_probability", predicted)
        object.__setattr__(self, "observed_positive_rate", observed)


@dataclass(frozen=True, slots=True)
class FeatureImportance:
    feature_key: str
    mean_metric_degradation: Decimal
    standard_deviation: Decimal
    repetitions: int

    def __init__(
        self,
        feature_key: str,
        mean_metric_degradation: DecimalInput,
        standard_deviation: DecimalInput,
        repetitions: int,
    ) -> None:
        key = feature_key.strip()
        degradation = to_decimal(
            mean_metric_degradation, field_name="mean metric degradation"
        )
        deviation = to_decimal(standard_deviation, field_name="importance deviation")
        if not key or repetitions <= 0 or deviation < 0:
            raise DomainValidationError("Invalid feature-importance evidence")
        object.__setattr__(self, "feature_key", key)
        object.__setattr__(self, "mean_metric_degradation", degradation)
        object.__setattr__(self, "standard_deviation", deviation)
        object.__setattr__(self, "repetitions", repetitions)


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    metric_name: str
    confidence_level: Decimal
    lower_bound: Decimal
    point_estimate: Decimal
    upper_bound: Decimal

    def __init__(
        self,
        metric_name: str,
        confidence_level: DecimalInput,
        lower_bound: DecimalInput,
        point_estimate: DecimalInput,
        upper_bound: DecimalInput,
    ) -> None:
        name = metric_name.strip().lower()
        confidence = to_decimal(confidence_level, field_name="confidence level")
        lower = to_decimal(lower_bound, field_name="confidence lower bound")
        point = to_decimal(point_estimate, field_name="confidence point estimate")
        upper = to_decimal(upper_bound, field_name="confidence upper bound")
        if not name or not Decimal(0) < confidence < Decimal(1):
            raise DomainValidationError("Invalid confidence-interval metadata")
        if not lower <= point <= upper:
            raise DomainValidationError("Confidence interval must contain point estimate")
        object.__setattr__(self, "metric_name", name)
        object.__setattr__(self, "confidence_level", confidence)
        object.__setattr__(self, "lower_bound", lower)
        object.__setattr__(self, "point_estimate", point)
        object.__setattr__(self, "upper_bound", upper)


@dataclass(frozen=True, slots=True)
class SliceEvaluation:
    slice_name: str
    slice_value: str
    sample_count: int
    metrics: tuple[MetricValue, ...]

    def __post_init__(self) -> None:
        if not self.slice_name.strip() or not self.slice_value.strip():
            raise DomainValidationError("Slice name and value are required")
        if self.sample_count <= 0 or not self.metrics:
            raise DomainValidationError("Slice evaluation requires samples and metrics")


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    task: LearningTask
    sample_count: int
    metrics: tuple[MetricValue, ...]
    calibration: tuple[CalibrationBin, ...]
    slices: tuple[SliceEvaluation, ...]
    generated_at: UtcInstant
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.sample_count <= 0 or not self.metrics:
            raise DomainValidationError("Evaluation report requires samples and metrics")
        names = tuple(item.name for item in self.metrics)
        if len(set(names)) != len(names):
            raise DomainValidationError("Evaluation metric names must be unique")
        ordered_metrics = tuple(sorted(self.metrics, key=lambda item: item.name))
        object.__setattr__(self, "metrics", ordered_metrics)
        payload = {
            "task": self.task.value,
            "sample_count": self.sample_count,
            "metrics": [
                {
                    "name": item.name,
                    "value": str(item.value),
                    "direction": item.direction.value,
                }
                for item in ordered_metrics
            ],
            "calibration": [
                {
                    "lower": str(item.lower_bound),
                    "upper": str(item.upper_bound),
                    "count": item.sample_count,
                    "predicted": str(item.mean_predicted_probability),
                    "observed": str(item.observed_positive_rate),
                }
                for item in self.calibration
            ],
            "slices": [
                {
                    "name": item.slice_name,
                    "value": item.slice_value,
                    "count": item.sample_count,
                    "metrics": [
                        (metric.name, str(metric.value)) for metric in item.metrics
                    ],
                }
                for item in self.slices
            ],
            "generated_at": self.generated_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    def metric(self, name: str) -> MetricValue:
        normalized = name.strip().lower()
        for metric in self.metrics:
            if metric.name == normalized:
                return metric
        raise DomainValidationError(f"Metric is not present in report: {normalized}")
