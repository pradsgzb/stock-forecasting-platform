from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from stock_predictor.adapters.models.baselines import RidgeRegressionPlugin
from stock_predictor.application.evaluation.service import (
    ModelEvaluationService,
    PermutationImportanceService,
    metric_direction,
)
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import EvaluationError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.evaluation import MetricDirection
from stock_predictor.domain.modeling.models import LearningTask
from tests.helpers.modeling import signature
from tests.unit.adapters.models.test_baselines import spec


def evaluator():
    return ModelEvaluationService(
        FixedClock(UtcInstant(datetime(2026, 1, 1, tzinfo=UTC)))
    )


def test_regression_metrics_and_slices_are_deterministic() -> None:
    actual = np.asarray([-1.0, -0.5, 0.0, 0.5, 1.0], dtype=np.float64)
    predicted = np.asarray([-0.8, -0.4, 0.1, 0.4, 0.9], dtype=np.float64)

    report = evaluator().evaluate(
        LearningTask.REGRESSION,
        actual,
        predicted,
        slices=(
            ("regime", "bear"),
            ("regime", "bear"),
            ("regime", "flat"),
            ("regime", "bull"),
            ("regime", "bull"),
        ),
    )

    assert report.metric("mae").value == Decimal("0.12")
    assert report.metric("directional_accuracy").value == Decimal("0.8")
    assert report.metric("r2").value > Decimal("0.9")
    assert len(report.slices) == 3
    assert report.calibration == ()


def test_classification_metrics_calibration_and_single_class_auc() -> None:
    actual = np.asarray([0, 0, 0, 1, 1, 1], dtype=np.float64)
    probabilities = np.asarray([0.1, 0.2, 0.4, 0.6, 0.8, 0.9], dtype=np.float64)
    predicted = (probabilities >= 0.5).astype(np.float64)

    report = evaluator().evaluate(
        LearningTask.BINARY_CLASSIFICATION,
        actual,
        predicted,
        positive_probability=probabilities,
        calibration_bins=3,
    )

    assert report.metric("accuracy").value == Decimal(1)
    assert report.metric("roc_auc").value == Decimal(1)
    assert report.metric("log_loss").value > 0
    assert sum(item.sample_count for item in report.calibration) == 6

    single_class = evaluator().evaluate(
        LearningTask.BINARY_CLASSIFICATION,
        np.zeros(3, dtype=np.float64),
        np.zeros(3, dtype=np.float64),
        positive_probability=np.asarray([0.1, 0.2, 0.3], dtype=np.float64),
    )
    assert single_class.metric("roc_auc").value == Decimal("0.5")


def test_interval_pinball_and_bootstrap_evidence() -> None:
    service = evaluator()
    actual = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
    predicted = np.asarray([0.1, 0.9, 2.1, 2.9], dtype=np.float64)
    coverage, width = service.interval_metrics(
        actual,
        predicted - 0.2,
        predicted + 0.2,
    )
    assert coverage.value == Decimal(1)
    assert width.value == Decimal("0.4")
    assert service.pinball_loss(actual, predicted, 0.5).value > 0

    interval = service.bootstrap_confidence_interval(
        LearningTask.REGRESSION,
        actual,
        predicted,
        "mae",
        repetitions=50,
        random_seed=4,
    )
    assert interval.lower_bound <= interval.point_estimate <= interval.upper_bound


def test_permutation_importance_identifies_predictive_feature() -> None:
    generator = np.random.default_rng(4)
    first = np.linspace(-2.0, 2.0, 80)
    second = generator.normal(0.0, 1.0, 80)
    features = np.column_stack((first, second)).astype(np.float64)
    actual = (first * 2.0).astype(np.float64)
    model = RidgeRegressionPlugin().fit(
        spec("linear.ridge", parameters=(("alpha", Decimal("0.01")),)),
        signature(),
        features,
        actual,
    )

    importances = PermutationImportanceService(evaluator()).calculate(
        model,
        features,
        actual,
        "mae",
        repetitions=3,
        random_seed=3,
    )

    assert importances[0].feature_key == "momentum@1.0.0"
    assert importances[0].mean_metric_degradation > importances[1].mean_metric_degradation


def test_evaluation_rejects_invalid_requests() -> None:
    service = evaluator()
    with pytest.raises(EvaluationError, match="non-empty"):
        service.evaluate(
            LearningTask.REGRESSION,
            np.asarray([], dtype=np.float64),
            np.asarray([], dtype=np.float64),
        )
    with pytest.raises(EvaluationError, match="same shape"):
        service.evaluate(
            LearningTask.REGRESSION,
            np.asarray([1.0], dtype=np.float64),
            np.asarray([1.0, 2.0], dtype=np.float64),
        )
    with pytest.raises(EvaluationError, match=r"within \[0, 1\]"):
        service.evaluate(
            LearningTask.BINARY_CLASSIFICATION,
            np.asarray([0.0, 1.0], dtype=np.float64),
            np.asarray([0.0, 1.0], dtype=np.float64),
            positive_probability=np.asarray([-0.1, 1.1], dtype=np.float64),
        )
    with pytest.raises(EvaluationError, match="between 2 and 100"):
        service.evaluate(
            LearningTask.BINARY_CLASSIFICATION,
            np.asarray([0.0, 1.0], dtype=np.float64),
            np.asarray([0.0, 1.0], dtype=np.float64),
            positive_probability=np.asarray([0.1, 0.9], dtype=np.float64),
            calibration_bins=1,
        )
    with pytest.raises(EvaluationError, match="lower bounds"):
        service.interval_metrics(
            np.asarray([1.0]),
            np.asarray([2.0]),
            np.asarray([1.0]),
        )
    with pytest.raises(EvaluationError, match="Invalid quantile"):
        service.pinball_loss(np.asarray([1.0]), np.asarray([1.0]), 1.0)
    with pytest.raises(EvaluationError, match="at least 50"):
        service.bootstrap_confidence_interval(
            LearningTask.REGRESSION,
            np.asarray([1.0]),
            np.asarray([1.0]),
            "mae",
            repetitions=10,
        )
    with pytest.raises(EvaluationError, match="Unknown"):
        metric_direction("unknown")
    assert metric_direction("mae") is MetricDirection.MINIMIZE
