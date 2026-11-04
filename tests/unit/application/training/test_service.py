from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from stock_predictor.adapters.experiments.in_memory_tracker import (
    InMemoryExperimentTracker,
)
from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.adapters.models.baselines import (
    FeatureEchoRegressorPlugin,
    HistoricalMeanRegressorPlugin,
    LogisticRegressionPlugin,
    MajorityClassifierPlugin,
    RidgeRegressionPlugin,
    ZeroReturnRegressorPlugin,
)
from stock_predictor.adapters.repositories.in_memory_dataset_repository import (
    InMemoryDatasetRepository,
)
from stock_predictor.application.evaluation.service import ModelEvaluationService
from stock_predictor.application.models.registry import ModelPluginRegistry
from stock_predictor.application.splitting.service import PurgedWalkForwardSplitter
from stock_predictor.application.training.service import (
    ModelTrainingService,
    TrainingRequest,
)
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import (
    DomainValidationError,
    TrainingPipelineError,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.experiments import ExperimentEventType
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelFamily,
    ModelSpec,
)
from stock_predictor.domain.modeling.splits import WalkForwardSplitConfig
from stock_predictor.domain.modeling.training import TrialStatus
from tests.helpers.modeling import make_dataset


def model_spec(name, plugin, *, task=LearningTask.REGRESSION, parameters=()):
    return ModelSpec(
        name,
        "1",
        ModelFamily.LINEAR if plugin.startswith("linear") else ModelFamily.BASELINE,
        task,
        plugin,
        10,
        parameters,
    )


def service_for(dataset, plugins):
    repository = InMemoryDatasetRepository()
    repository.put(dataset)
    clock = FixedClock(UtcInstant(datetime(2026, 2, 1, tzinfo=UTC)))
    tracker = InMemoryExperimentTracker()
    codec = TrustedJoblibArtifactCodec()
    return (
        ModelTrainingService(
            repository,
            ModelPluginRegistry(plugins),
            ModelEvaluationService(clock),
            codec,
            tracker,
            clock,
        ),
        tracker,
        codec,
    )


def split(dataset):
    return PurgedWalkForwardSplitter().split(
        dataset,
        WalkForwardSplitConfig(
            minimum_train_periods=8,
            validation_periods=4,
            step_periods=4,
            final_holdout_periods=4,
            gap_periods=1,
        ),
    )


def test_training_service_selects_candidate_without_tuning_on_holdout() -> None:
    dataset = make_dataset(periods=32)
    training, tracker, _ = service_for(
        dataset,
        (
            ZeroReturnRegressorPlugin(),
            HistoricalMeanRegressorPlugin(),
            RidgeRegressionPlugin(),
        ),
    )
    candidates = (
        model_spec("zero", "baseline.zero_return"),
        model_spec("mean", "baseline.historical_mean"),
        model_spec(
            "ridge",
            "linear.ridge",
            parameters=(("alpha", Decimal("0.001")),),
        ),
        model_spec(
            "wrong_task",
            "linear.logistic",
            task=LearningTask.BINARY_CLASSIFICATION,
        ),
    )

    result = training.train(
        TrainingRequest(
            experiment_name="regression-selection",
            dataset_version_id=dataset.dataset_version_id,
            split_plan=split(dataset),
            candidates=candidates,
            primary_metric="mae",
            baseline_plugin_keys=(
                "baseline.zero_return",
                "baseline.historical_mean",
            ),
        )
    )

    assert result.selected_spec.plugin_key == "linear.ridge"
    assert result.holdout_report.sample_count == 4
    assert result.artifact.payload_sha256
    assert result.model_card.training_dataset_fingerprint == dataset.fingerprint
    assert any(item.status is TrialStatus.FAILED for item in result.trials)
    events = tracker.events(result.run_id)
    assert events[0].event_type is ExperimentEventType.STARTED
    assert events[-1].event_type is ExperimentEventType.COMPLETED
    assert [item.sequence for item in events] == list(range(1, len(events) + 1))

    loaded = TrustedJoblibArtifactCodec(allow_deserialization=True).deserialize(
        result.artifact
    )
    predictions = loaded.predict(np.asarray([[0.1, 0.2]], dtype=np.float64))
    assert predictions.shape == (1,)


def test_training_service_supports_binary_classification() -> None:
    dataset = make_dataset(periods=32, classification=True)
    training, _, _ = service_for(
        dataset,
        (MajorityClassifierPlugin(), LogisticRegressionPlugin()),
    )
    result = training.train(
        TrainingRequest(
            experiment_name="classification-selection",
            dataset_version_id=dataset.dataset_version_id,
            split_plan=split(dataset),
            candidates=(
                model_spec(
                    "majority",
                    "baseline.majority_classifier",
                    task=LearningTask.BINARY_CLASSIFICATION,
                ),
                model_spec(
                    "logistic",
                    "linear.logistic",
                    task=LearningTask.BINARY_CLASSIFICATION,
                    parameters=(("max_iter", 200),),
                ),
            ),
            primary_metric="log_loss",
            baseline_plugin_keys=("baseline.majority_classifier",),
        )
    )
    assert result.holdout_report.task is LearningTask.BINARY_CLASSIFICATION
    assert result.holdout_report.metric("log_loss").value >= 0


def test_training_service_requires_completed_baseline_and_records_failure() -> None:
    dataset = make_dataset(periods=20)
    training, tracker, _ = service_for(dataset, (RidgeRegressionPlugin(),))
    request = TrainingRequest(
        experiment_name="missing-baseline",
        dataset_version_id=dataset.dataset_version_id,
        split_plan=split(dataset),
        candidates=(
            model_spec("zero", "baseline.zero_return"),
            model_spec("ridge", "linear.ridge"),
        ),
        primary_metric="mae",
        baseline_plugin_keys=("baseline.zero_return",),
    )

    with pytest.raises(TrainingPipelineError, match="baseline"):
        training.train(request)

    run_events = next(iter(tracker._events.values()))
    assert run_events[-1].event_type is ExperimentEventType.FAILED


def test_training_service_fails_when_all_candidates_fail() -> None:
    dataset = make_dataset(periods=20)
    training, _, _ = service_for(
        dataset,
        (ZeroReturnRegressorPlugin(), RidgeRegressionPlugin()),
    )
    bad = model_spec(
        "ridge",
        "linear.ridge",
        parameters=(("alpha", Decimal("-1")),),
    )
    wrong_task_baseline = model_spec(
        "zero",
        "baseline.zero_return",
        task=LearningTask.BINARY_CLASSIFICATION,
    )
    with pytest.raises(TrainingPipelineError, match="Every model"):
        training.train(
            TrainingRequest(
                experiment_name="all-fail",
                dataset_version_id=dataset.dataset_version_id,
                split_plan=split(dataset),
                candidates=(bad, wrong_task_baseline),
                primary_metric="mae",
                baseline_plugin_keys=("baseline.zero_return",),
            )
        )


def test_training_request_requires_declared_baseline_candidates() -> None:
    dataset = make_dataset(periods=20)
    plan = split(dataset)
    zero = model_spec("zero", "baseline.zero_return")

    with pytest.raises(DomainValidationError, match="baseline plugin key"):
        TrainingRequest(
            experiment_name="no-baseline",
            dataset_version_id=dataset.dataset_version_id,
            split_plan=plan,
            candidates=(zero,),
            primary_metric="mae",
            baseline_plugin_keys=(),
        )

    with pytest.raises(DomainValidationError, match="also be model candidates"):
        TrainingRequest(
            experiment_name="missing-candidate",
            dataset_version_id=dataset.dataset_version_id,
            split_plan=plan,
            candidates=(zero,),
            primary_metric="mae",
            baseline_plugin_keys=("baseline.historical_mean",),
        )


def test_training_requires_every_declared_baseline_to_complete() -> None:
    dataset = make_dataset(periods=20)
    training, _, _ = service_for(
        dataset,
        (
            ZeroReturnRegressorPlugin(),
            FeatureEchoRegressorPlugin(),
            RidgeRegressionPlugin(),
        ),
    )
    with pytest.raises(TrainingPipelineError, match="baseline.feature_echo"):
        training.train(
            TrainingRequest(
                experiment_name="all-baselines-required",
                dataset_version_id=dataset.dataset_version_id,
                split_plan=split(dataset),
                candidates=(
                    model_spec("zero", "baseline.zero_return"),
                    model_spec("echo", "baseline.feature_echo"),
                    model_spec("ridge", "linear.ridge"),
                ),
                primary_metric="mae",
                baseline_plugin_keys=(
                    "baseline.zero_return",
                    "baseline.feature_echo",
                ),
            )
        )
