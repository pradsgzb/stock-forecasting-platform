"""Deterministic predictive metrics, calibration, confidence, and robustness analysis."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import EvaluationError
from stock_predictor.domain.modeling.evaluation import (
    CalibrationBin,
    ConfidenceInterval,
    EvaluationReport,
    FeatureImportance,
    MetricDirection,
    MetricValue,
    SliceEvaluation,
)
from stock_predictor.domain.modeling.models import LearningTask
from stock_predictor.ports.model_plugin import FittedModel, FloatMatrix, FloatVector

_METRIC_DIRECTIONS: dict[str, MetricDirection] = {
    "mae": MetricDirection.MINIMIZE,
    "rmse": MetricDirection.MINIMIZE,
    "median_absolute_error": MetricDirection.MINIMIZE,
    "r2": MetricDirection.MAXIMIZE,
    "directional_accuracy": MetricDirection.MAXIMIZE,
    "pearson_correlation": MetricDirection.MAXIMIZE,
    "spearman_rank_correlation": MetricDirection.MAXIMIZE,
    "accuracy": MetricDirection.MAXIMIZE,
    "balanced_accuracy": MetricDirection.MAXIMIZE,
    "precision": MetricDirection.MAXIMIZE,
    "recall": MetricDirection.MAXIMIZE,
    "roc_auc": MetricDirection.MAXIMIZE,
    "log_loss": MetricDirection.MINIMIZE,
    "brier_score": MetricDirection.MINIMIZE,
    "expected_calibration_error": MetricDirection.MINIMIZE,
    "pinball_loss": MetricDirection.MINIMIZE,
    "interval_coverage": MetricDirection.MAXIMIZE,
    "mean_interval_width": MetricDirection.MINIMIZE,
}


def metric_direction(name: str) -> MetricDirection:
    normalized = name.strip().lower()
    try:
        return _METRIC_DIRECTIONS[normalized]
    except KeyError as exc:
        raise EvaluationError(f"Unknown evaluation metric: {normalized}") from exc


def _decimal(value: float) -> Decimal:
    if not np.isfinite(value):
        raise EvaluationError("Evaluation metric is not finite")
    # Canonicalize binary floating-point output for stable, human-readable evidence.
    return Decimal(format(float(value), ".15g"))


def _validate_vector(name: str, values: FloatVector) -> None:
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise EvaluationError(f"{name} must be a non-empty finite one-dimensional vector")


def _average_ranks(values: FloatVector) -> FloatVector:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + end - 1) / 2.0 + 1.0
        ranks[order[start:end]] = average
        start = end
    return ranks


def _correlation(left: FloatVector, right: FloatVector) -> float:
    if np.std(left) == 0 or np.std(right) == 0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


class ModelEvaluationService:
    """Produces immutable reports for regression and binary classification."""

    __slots__ = ("_clock",)

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def evaluate(
        self,
        task: LearningTask,
        actual: FloatVector,
        predicted: FloatVector,
        *,
        positive_probability: FloatVector | None = None,
        calibration_bins: int = 10,
        slices: tuple[tuple[str, str], ...] | None = None,
    ) -> EvaluationReport:
        _validate_vector("actual", actual)
        _validate_vector("predicted", predicted)
        if actual.shape != predicted.shape:
            raise EvaluationError("Actual and predicted vectors must have the same shape")
        if task is LearningTask.REGRESSION:
            metrics = self._regression_metrics(actual, predicted)
            calibration: tuple[CalibrationBin, ...] = ()
        else:
            probabilities = positive_probability
            if probabilities is None:
                probabilities = np.clip(predicted, 0.0, 1.0)
            _validate_vector("positive_probability", probabilities)
            if probabilities.shape != actual.shape:
                raise EvaluationError("Probability vector must match actual labels")
            metrics, calibration = self._classification_metrics(
                actual,
                predicted,
                probabilities,
                calibration_bins,
            )
        slice_reports: tuple[SliceEvaluation, ...] = ()
        if slices is not None:
            if len(slices) != actual.size:
                raise EvaluationError("Slice labels must match evaluation rows")
            slice_reports = self._slice_reports(
                task,
                actual,
                predicted,
                positive_probability,
                slices,
                calibration_bins,
            )
        return EvaluationReport(
            task=task,
            sample_count=int(actual.size),
            metrics=metrics,
            calibration=calibration,
            slices=slice_reports,
            generated_at=self._clock.now(),
        )

    @staticmethod
    def _regression_metrics(
        actual: FloatVector,
        predicted: FloatVector,
    ) -> tuple[MetricValue, ...]:
        errors = predicted - actual
        absolute = np.abs(errors)
        residual_sum = float(np.sum(errors**2))
        centered_sum = float(np.sum((actual - np.mean(actual)) ** 2))
        if centered_sum == 0:
            r2 = 1.0 if residual_sum == 0 else 0.0
        else:
            r2 = 1.0 - residual_sum / centered_sum
        directional = float(np.mean(np.sign(actual) == np.sign(predicted)))
        return (
            MetricValue("mae", _decimal(float(np.mean(absolute))), MetricDirection.MINIMIZE),
            MetricValue(
                "rmse",
                _decimal(float(np.sqrt(np.mean(errors**2)))),
                MetricDirection.MINIMIZE,
            ),
            MetricValue(
                "median_absolute_error",
                _decimal(float(np.median(absolute))),
                MetricDirection.MINIMIZE,
            ),
            MetricValue("r2", _decimal(r2), MetricDirection.MAXIMIZE),
            MetricValue(
                "directional_accuracy",
                _decimal(directional),
                MetricDirection.MAXIMIZE,
            ),
            MetricValue(
                "pearson_correlation",
                _decimal(_correlation(actual, predicted)),
                MetricDirection.MAXIMIZE,
            ),
            MetricValue(
                "spearman_rank_correlation",
                _decimal(
                    _correlation(_average_ranks(actual), _average_ranks(predicted))
                ),
                MetricDirection.MAXIMIZE,
            ),
        )

    @staticmethod
    def _classification_metrics(
        actual: FloatVector,
        predicted: FloatVector,
        probabilities: FloatVector,
        calibration_bins: int,
    ) -> tuple[tuple[MetricValue, ...], tuple[CalibrationBin, ...]]:
        if not np.isin(actual, (0.0, 1.0)).all():
            raise EvaluationError("Binary evaluation labels must be 0 or 1")
        if np.any((probabilities < 0) | (probabilities > 1)):
            raise EvaluationError("Binary probabilities must be within [0, 1]")
        labels = (predicted >= 0.5).astype(np.float64)
        true_positive = float(np.sum((labels == 1) & (actual == 1)))
        true_negative = float(np.sum((labels == 0) & (actual == 0)))
        false_positive = float(np.sum((labels == 1) & (actual == 0)))
        false_negative = float(np.sum((labels == 0) & (actual == 1)))
        positive_count = true_positive + false_negative
        negative_count = true_negative + false_positive
        precision = true_positive / (true_positive + false_positive) if (
            true_positive + false_positive
        ) else 0.0
        recall = true_positive / positive_count if positive_count else 0.0
        specificity = true_negative / negative_count if negative_count else 0.0
        balanced = (recall + specificity) / 2.0
        epsilon = np.finfo(np.float64).eps
        clipped = np.clip(probabilities, epsilon, 1.0 - epsilon)
        log_loss = -float(
            np.mean(actual * np.log(clipped) + (1.0 - actual) * np.log(1.0 - clipped))
        )
        calibration = ModelEvaluationService._calibration_bins(
            actual,
            probabilities,
            calibration_bins,
        )
        expected_calibration_error = sum(
            (
                Decimal(item.sample_count)
                / Decimal(actual.size)
                * abs(
                    item.mean_predicted_probability - item.observed_positive_rate
                )
            )
            for item in calibration
        )
        metrics = (
            MetricValue(
                "accuracy",
                _decimal(float(np.mean(labels == actual))),
                MetricDirection.MAXIMIZE,
            ),
            MetricValue(
                "balanced_accuracy", _decimal(balanced), MetricDirection.MAXIMIZE
            ),
            MetricValue("precision", _decimal(precision), MetricDirection.MAXIMIZE),
            MetricValue("recall", _decimal(recall), MetricDirection.MAXIMIZE),
            MetricValue(
                "roc_auc",
                _decimal(ModelEvaluationService._roc_auc(actual, probabilities)),
                MetricDirection.MAXIMIZE,
            ),
            MetricValue("log_loss", _decimal(log_loss), MetricDirection.MINIMIZE),
            MetricValue(
                "brier_score",
                _decimal(float(np.mean((probabilities - actual) ** 2))),
                MetricDirection.MINIMIZE,
            ),
            MetricValue(
                "expected_calibration_error",
                expected_calibration_error,
                MetricDirection.MINIMIZE,
            ),
        )
        return metrics, calibration

    @staticmethod
    def _roc_auc(actual: FloatVector, probabilities: FloatVector) -> float:
        positives = actual == 1
        positive_count = int(np.sum(positives))
        negative_count = int(actual.size - positive_count)
        if positive_count == 0 or negative_count == 0:
            return 0.5
        ranks = _average_ranks(probabilities)
        positive_rank_sum = float(np.sum(ranks[positives]))
        return (
            positive_rank_sum - positive_count * (positive_count + 1) / 2.0
        ) / (positive_count * negative_count)

    @staticmethod
    def _calibration_bins(
        actual: FloatVector,
        probabilities: FloatVector,
        bin_count: int,
    ) -> tuple[CalibrationBin, ...]:
        if bin_count < 2 or bin_count > 100:
            raise EvaluationError("Calibration bin count must be between 2 and 100")
        edges = np.linspace(0.0, 1.0, bin_count + 1)
        result: list[CalibrationBin] = []
        for index in range(bin_count):
            lower = edges[index]
            upper = edges[index + 1]
            if index == bin_count - 1:
                mask = (probabilities >= lower) & (probabilities <= upper)
            else:
                mask = (probabilities >= lower) & (probabilities < upper)
            if not np.any(mask):
                continue
            result.append(
                CalibrationBin(
                    lower_bound=Decimal(str(lower)),
                    upper_bound=Decimal(str(upper)),
                    sample_count=int(np.sum(mask)),
                    mean_predicted_probability=Decimal(
                        str(float(np.mean(probabilities[mask])))
                    ),
                    observed_positive_rate=Decimal(
                        str(float(np.mean(actual[mask])))
                    ),
                )
            )
        return tuple(result)

    def _slice_reports(
        self,
        task: LearningTask,
        actual: FloatVector,
        predicted: FloatVector,
        probabilities: FloatVector | None,
        slices: tuple[tuple[str, str], ...],
        calibration_bins: int,
    ) -> tuple[SliceEvaluation, ...]:
        grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
        for index, key in enumerate(slices):
            grouped[key].append(index)
        reports: list[SliceEvaluation] = []
        for (slice_name, slice_value), indices in sorted(grouped.items()):
            selected = np.asarray(indices, dtype=np.int64)
            if task is LearningTask.REGRESSION:
                metrics = self._regression_metrics(actual[selected], predicted[selected])
            else:
                selected_probabilities = (
                    np.clip(predicted[selected], 0.0, 1.0)
                    if probabilities is None
                    else probabilities[selected]
                )
                metrics, _ = self._classification_metrics(
                    actual[selected],
                    predicted[selected],
                    selected_probabilities,
                    calibration_bins,
                )
            reports.append(
                SliceEvaluation(
                    slice_name=slice_name,
                    slice_value=slice_value,
                    sample_count=len(indices),
                    metrics=metrics,
                )
            )
        return tuple(reports)

    def interval_metrics(
        self,
        actual: FloatVector,
        lower: FloatVector,
        upper: FloatVector,
    ) -> tuple[MetricValue, MetricValue]:
        _validate_vector("actual", actual)
        _validate_vector("lower", lower)
        _validate_vector("upper", upper)
        if actual.shape != lower.shape or actual.shape != upper.shape:
            raise EvaluationError("Prediction intervals must match actual values")
        if np.any(lower > upper):
            raise EvaluationError("Prediction interval lower bounds cannot exceed upper bounds")
        coverage = float(np.mean((actual >= lower) & (actual <= upper)))
        width = float(np.mean(upper - lower))
        return (
            MetricValue("interval_coverage", _decimal(coverage), MetricDirection.MAXIMIZE),
            MetricValue(
                "mean_interval_width", _decimal(width), MetricDirection.MINIMIZE
            ),
        )

    def pinball_loss(
        self,
        actual: FloatVector,
        quantile_prediction: FloatVector,
        quantile: float,
    ) -> MetricValue:
        _validate_vector("actual", actual)
        _validate_vector("quantile_prediction", quantile_prediction)
        if actual.shape != quantile_prediction.shape or not 0.0 < quantile < 1.0:
            raise EvaluationError("Invalid quantile-evaluation request")
        errors = actual - quantile_prediction
        losses = np.maximum(quantile * errors, (quantile - 1.0) * errors)
        return MetricValue(
            "pinball_loss",
            _decimal(float(np.mean(losses))),
            MetricDirection.MINIMIZE,
        )

    def bootstrap_confidence_interval(
        self,
        task: LearningTask,
        actual: FloatVector,
        predicted: FloatVector,
        metric_name: str,
        *,
        positive_probability: FloatVector | None = None,
        confidence_level: float = 0.95,
        repetitions: int = 500,
        random_seed: int = 0,
    ) -> ConfidenceInterval:
        if not 0.0 < confidence_level < 1.0 or repetitions < 50:
            raise EvaluationError(
                "Bootstrap requires confidence in (0, 1) and at least 50 repetitions"
            )
        point = self.evaluate(
            task,
            actual,
            predicted,
            positive_probability=positive_probability,
        ).metric(metric_name)
        generator = np.random.default_rng(random_seed)
        values: list[float] = []
        for _ in range(repetitions):
            indices = generator.integers(0, actual.size, actual.size)
            report = self.evaluate(
                task,
                actual[indices],
                predicted[indices],
                positive_probability=(
                    None
                    if positive_probability is None
                    else positive_probability[indices]
                ),
            )
            values.append(float(report.metric(metric_name).value))
        alpha = (1.0 - confidence_level) / 2.0
        lower, upper = np.quantile(np.asarray(values), (alpha, 1.0 - alpha))
        return ConfidenceInterval(
            metric_name=metric_name,
            confidence_level=Decimal(str(confidence_level)),
            lower_bound=Decimal(str(float(lower))),
            point_estimate=point.value,
            upper_bound=Decimal(str(float(upper))),
        )


class PermutationImportanceService:
    """Model-agnostic importance measured as out-of-sample metric degradation."""

    __slots__ = ("_evaluator",)

    def __init__(self, evaluator: ModelEvaluationService) -> None:
        self._evaluator = evaluator

    def calculate(
        self,
        model: FittedModel,
        features: FloatMatrix,
        actual: FloatVector,
        metric_name: str,
        *,
        repetitions: int = 5,
        random_seed: int = 0,
    ) -> tuple[FeatureImportance, ...]:
        if repetitions <= 0:
            raise EvaluationError("Permutation repetitions must be positive")
        predicted = model.predict(features)
        probabilities = model.predict_positive_probability(features)
        baseline = self._evaluator.evaluate(
            model.signature.task,
            actual,
            predicted,
            positive_probability=probabilities,
        ).metric(metric_name)
        generator = np.random.default_rng(random_seed)
        result: list[FeatureImportance] = []
        for feature_index, feature_key in enumerate(model.signature.feature_keys):
            degradations: list[float] = []
            for _ in range(repetitions):
                permuted = features.copy()
                permuted[:, feature_index] = generator.permutation(
                    permuted[:, feature_index]
                )
                permuted_prediction = model.predict(permuted)
                permuted_probability = model.predict_positive_probability(permuted)
                metric = self._evaluator.evaluate(
                    model.signature.task,
                    actual,
                    permuted_prediction,
                    positive_probability=permuted_probability,
                ).metric(metric_name)
                degradation = (
                    float(metric.value - baseline.value)
                    if baseline.direction is MetricDirection.MINIMIZE
                    else float(baseline.value - metric.value)
                )
                degradations.append(degradation)
            result.append(
                FeatureImportance(
                    feature_key=feature_key,
                    mean_metric_degradation=Decimal(str(float(np.mean(degradations)))),
                    standard_deviation=Decimal(str(float(np.std(degradations)))),
                    repetitions=repetitions,
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda item: item.mean_metric_degradation,
                reverse=True,
            )
        )
