"""Leakage-aware cross-validation, tuning, selection, and final model fitting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from stock_predictor.application.evaluation.service import (
    ModelEvaluationService,
    metric_direction,
)
from stock_predictor.application.models.registry import ModelPluginRegistry
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import (
    DomainError,
    DomainValidationError,
    TrainingPipelineError,
)
from stock_predictor.domain.common.identifiers import (
    DatasetVersionId,
    ExperimentRunId,
    ModelVersionId,
)
from stock_predictor.domain.modeling.datasets import DatasetSnapshot
from stock_predictor.domain.modeling.evaluation import MetricDirection
from stock_predictor.domain.modeling.experiments import (
    ExperimentEvent,
    ExperimentEventType,
)
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelCard,
    ModelSignature,
    ModelSpec,
)
from stock_predictor.domain.modeling.splits import DatasetSplitPlan
from stock_predictor.domain.modeling.targets import TargetValueType
from stock_predictor.domain.modeling.training import (
    TrainingResult,
    TrialStatus,
    TrialSummary,
)
from stock_predictor.ports.dataset_repository import DatasetRepository
from stock_predictor.ports.experiment_tracker import ExperimentTracker
from stock_predictor.ports.model_plugin import (
    FloatMatrix,
    FloatVector,
    ModelArtifactCodec,
)


@dataclass(frozen=True, slots=True)
class TrainingRequest:
    experiment_name: str
    dataset_version_id: DatasetVersionId
    split_plan: DatasetSplitPlan
    candidates: tuple[ModelSpec, ...]
    primary_metric: str
    baseline_plugin_keys: tuple[str, ...]
    intended_use: str = "Research-only forecasting and paper-trading evaluation."
    prohibited_uses: tuple[str, ...] = (
        "Autonomous live trading",
        "Guaranteed-return claims",
        "Use without point-in-time data validation",
    )
    limitations: tuple[str, ...] = (
        "Historical performance may not persist.",
        "The model does not estimate every market, liquidity, or execution risk.",
        "Human review is required before any deployment or capital allocation.",
    )

    def __post_init__(self) -> None:
        if not self.experiment_name.strip() or not self.primary_metric.strip():
            raise DomainValidationError("Experiment name and primary metric are required")
        if not self.candidates:
            raise DomainValidationError("Training requires at least one model candidate")
        fingerprints = tuple(item.fingerprint for item in self.candidates)
        if len(set(fingerprints)) != len(fingerprints):
            raise DomainValidationError("Model candidates must be unique")
        if self.split_plan.dataset_version_id != self.dataset_version_id:
            raise DomainValidationError("Split plan belongs to a different dataset")
        normalized_baselines = tuple(
            item.strip().lower() for item in self.baseline_plugin_keys
        )
        if not normalized_baselines or any(not item for item in normalized_baselines):
            raise DomainValidationError("At least one baseline plugin key is required")
        if len(set(normalized_baselines)) != len(normalized_baselines):
            raise DomainValidationError("Baseline plugin keys must be unique")
        candidate_plugins = {item.plugin_key for item in self.candidates}
        missing_candidates = sorted(set(normalized_baselines) - candidate_plugins)
        if missing_candidates:
            raise DomainValidationError(
                "Required baselines must also be model candidates: "
                + ", ".join(missing_candidates)
            )
        object.__setattr__(self, "baseline_plugin_keys", normalized_baselines)


class _ExperimentWriter:
    __slots__ = ("_clock", "_run_id", "_sequence", "_tracker")

    def __init__(
        self,
        run_id: ExperimentRunId,
        tracker: ExperimentTracker,
        clock: Clock,
    ) -> None:
        self._run_id = run_id
        self._tracker = tracker
        self._clock = clock
        self._sequence = 0

    def append(
        self,
        event_type: ExperimentEventType,
        **details: str | int | bool | None,
    ) -> None:
        self._sequence += 1
        self._tracker.append(
            ExperimentEvent.create(
                self._run_id,
                self._sequence,
                event_type,
                self._clock.now(),
                details,
            )
        )


class ModelTrainingService:
    """Runs tuning on development folds and touches final holdout only after selection."""

    __slots__ = (
        "_artifacts",
        "_clock",
        "_datasets",
        "_evaluator",
        "_plugins",
        "_tracker",
    )

    def __init__(
        self,
        datasets: DatasetRepository,
        plugins: ModelPluginRegistry,
        evaluator: ModelEvaluationService,
        artifacts: ModelArtifactCodec,
        tracker: ExperimentTracker,
        clock: Clock,
    ) -> None:
        self._datasets = datasets
        self._plugins = plugins
        self._evaluator = evaluator
        self._artifacts = artifacts
        self._tracker = tracker
        self._clock = clock

    def train(self, request: TrainingRequest) -> TrainingResult:
        run_id = ExperimentRunId.new()
        writer = _ExperimentWriter(run_id, self._tracker, self._clock)
        dataset = self._datasets.get(request.dataset_version_id)
        task = self._task_for(dataset)
        signature = ModelSignature(dataset.feature_keys, dataset.target.key, task)
        direction = metric_direction(request.primary_metric)
        writer.append(
            ExperimentEventType.STARTED,
            experiment_name=request.experiment_name,
            dataset_fingerprint=dataset.fingerprint,
            split_plan_fingerprint=request.split_plan.fingerprint,
            primary_metric=request.primary_metric.strip().lower(),
            candidate_count=len(request.candidates),
        )
        try:
            trials = self._cross_validate(
                dataset,
                request,
                signature,
                direction,
                writer,
            )
            selected = self._select(trials, direction)
            completed_baselines = tuple(
                item
                for item in trials
                if item.status is TrialStatus.COMPLETED
                and item.spec.plugin_key in request.baseline_plugin_keys
            )
            completed_baseline_keys = {
                item.spec.plugin_key for item in completed_baselines
            }
            missing_baselines = tuple(
                key
                for key in request.baseline_plugin_keys
                if key not in completed_baseline_keys
            )
            if missing_baselines:
                raise TrainingPipelineError(
                    "Required baselines did not complete successfully: "
                    + ", ".join(missing_baselines)
                )
            writer.append(
                ExperimentEventType.CANDIDATE_SELECTED,
                spec_fingerprint=selected.spec.fingerprint,
                plugin_key=selected.spec.plugin_key,
                cross_validation_score=str(selected.mean_score),
                baseline_count=len(completed_baselines),
            )
            development = self._matrix(dataset, request.split_plan.development_indices)
            holdout = self._matrix(dataset, request.split_plan.holdout_indices)
            plugin = self._plugins.get(selected.spec.plugin_key, task)
            fitted = plugin.fit(
                selected.spec,
                signature,
                development.features,
                development.target,
                development.sample_weight,
            )
            fitted.health_check()
            holdout_prediction = fitted.predict(holdout.features)
            holdout_probability = fitted.predict_positive_probability(holdout.features)
            holdout_report = self._evaluator.evaluate(
                task,
                holdout.target,
                holdout_prediction,
                positive_probability=holdout_probability,
            )
            holdout_metric = holdout_report.metric(request.primary_metric)
            writer.append(
                ExperimentEventType.HOLDOUT_EVALUATED,
                report_fingerprint=holdout_report.fingerprint,
                score=str(holdout_metric.value),
                sample_count=holdout_report.sample_count,
            )
            model_version_id = ModelVersionId.new()
            artifact = self._artifacts.serialize(
                fitted,
                model_version_id,
                self._clock.now(),
            )
            model_card = ModelCard.create(
                model_version_id=model_version_id,
                spec=selected.spec,
                intended_use=request.intended_use,
                prohibited_uses=request.prohibited_uses,
                training_dataset_fingerprint=dataset.fingerprint,
                split_plan_fingerprint=request.split_plan.fingerprint,
                primary_metric=request.primary_metric,
                cross_validation_score=self._required_score(selected),
                holdout_score=holdout_metric.value,
                limitations=request.limitations,
                generated_at=self._clock.now(),
            )
            writer.append(
                ExperimentEventType.ARTIFACT_CREATED,
                model_version_id=str(model_version_id),
                artifact_id=str(artifact.artifact_id),
                artifact_sha256=artifact.payload_sha256,
            )
            writer.append(
                ExperimentEventType.COMPLETED,
                model_version_id=str(model_version_id),
                selected_plugin=selected.spec.plugin_key,
                holdout_report=holdout_report.fingerprint,
            )
            return TrainingResult(
                run_id=run_id,
                model_version_id=model_version_id,
                selected_spec=selected.spec,
                primary_metric=request.primary_metric.strip().lower(),
                cross_validation_score=self._required_score(selected),
                holdout_report=holdout_report,
                artifact=artifact,
                model_card=model_card,
                trials=trials,
            )
        except Exception as exc:  # noqa: BLE001 - record terminal pipeline failures
            writer.append(
                ExperimentEventType.FAILED,
                error_type=type(exc).__name__,
                reason=str(exc)[:500],
            )
            raise

    def _cross_validate(
        self,
        dataset: DatasetSnapshot,
        request: TrainingRequest,
        signature: ModelSignature,
        direction: MetricDirection,
        writer: _ExperimentWriter,
    ) -> tuple[TrialSummary, ...]:
        trials: list[TrialSummary] = []
        for trial_number, spec in enumerate(request.candidates, 1):
            if spec.task is not signature.task:
                reason = "Candidate task does not match dataset target"
                trial = TrialSummary(
                    trial_number=trial_number,
                    spec=spec,
                    status=TrialStatus.FAILED,
                    fold_scores=(),
                    mean_score=None,
                    metric_name=request.primary_metric,
                    metric_direction=direction,
                    failure_reason=reason,
                )
                trials.append(trial)
                writer.append(
                    ExperimentEventType.TRIAL_FAILED,
                    trial_number=trial_number,
                    spec_fingerprint=spec.fingerprint,
                    reason=reason,
                )
                continue
            try:
                plugin = self._plugins.get(spec.plugin_key, spec.task)
                fold_scores: list[Decimal] = []
                for fold in request.split_plan.folds:
                    train = self._matrix(dataset, fold.train_indices)
                    validation = self._matrix(dataset, fold.validation_indices)
                    model = plugin.fit(
                        spec,
                        signature,
                        train.features,
                        train.target,
                        train.sample_weight,
                    )
                    prediction = model.predict(validation.features)
                    probability = model.predict_positive_probability(validation.features)
                    report = self._evaluator.evaluate(
                        spec.task,
                        validation.target,
                        prediction,
                        positive_probability=probability,
                    )
                    fold_scores.append(report.metric(request.primary_metric).value)
                mean_score = sum(fold_scores, start=Decimal(0)) / Decimal(
                    len(fold_scores)
                )
                trial = TrialSummary(
                    trial_number=trial_number,
                    spec=spec,
                    status=TrialStatus.COMPLETED,
                    fold_scores=tuple(fold_scores),
                    mean_score=mean_score,
                    metric_name=request.primary_metric,
                    metric_direction=direction,
                )
                trials.append(trial)
                writer.append(
                    ExperimentEventType.TRIAL_COMPLETED,
                    trial_number=trial_number,
                    spec_fingerprint=spec.fingerprint,
                    plugin_key=spec.plugin_key,
                    mean_score=str(mean_score),
                    fold_count=len(fold_scores),
                )
            except (DomainError, ValueError, FloatingPointError) as exc:
                trial = TrialSummary(
                    trial_number=trial_number,
                    spec=spec,
                    status=TrialStatus.FAILED,
                    fold_scores=(),
                    mean_score=None,
                    metric_name=request.primary_metric,
                    metric_direction=direction,
                    failure_reason=str(exc)[:500],
                )
                trials.append(trial)
                writer.append(
                    ExperimentEventType.TRIAL_FAILED,
                    trial_number=trial_number,
                    spec_fingerprint=spec.fingerprint,
                    reason=str(exc)[:500],
                )
        return tuple(trials)

    @staticmethod
    def _select(
        trials: tuple[TrialSummary, ...],
        direction: MetricDirection,
    ) -> TrialSummary:
        completed = tuple(
            item for item in trials if item.status is TrialStatus.COMPLETED
        )
        if not completed:
            raise TrainingPipelineError("Every model candidate failed")
        if direction is MetricDirection.MINIMIZE:
            return min(completed, key=ModelTrainingService._required_score)
        return max(completed, key=ModelTrainingService._required_score)

    @staticmethod
    def _required_score(trial: TrialSummary) -> Decimal:
        if trial.mean_score is None:
            raise TrainingPipelineError("Completed trial has no mean score")
        return trial.mean_score

    @staticmethod
    def _task_for(dataset: DatasetSnapshot) -> LearningTask:
        if dataset.target.value_type is TargetValueType.BINARY:
            return LearningTask.BINARY_CLASSIFICATION
        return LearningTask.REGRESSION

    @staticmethod
    def _matrix(
        dataset: DatasetSnapshot,
        indices: tuple[int, ...],
    ) -> _DatasetMatrix:
        if not indices or len(set(indices)) != len(indices):
            raise TrainingPipelineError("Dataset matrix indices must be unique and non-empty")
        if min(indices) < 0 or max(indices) >= dataset.row_count:
            raise TrainingPipelineError("Dataset matrix index is outside dataset bounds")
        rows = tuple(dataset.rows[index] for index in indices)
        features = np.asarray(
            [[float(value) for value in row.feature_values] for row in rows],
            dtype=np.float64,
        )
        target = np.asarray(
            [float(row.target_value) for row in rows],
            dtype=np.float64,
        )
        sample_weight = np.asarray(
            [float(row.sample_weight) for row in rows],
            dtype=np.float64,
        )
        if not (
            np.isfinite(features).all()
            and np.isfinite(target).all()
            and np.isfinite(sample_weight).all()
        ):
            raise TrainingPipelineError("Dataset conversion produced non-finite values")
        return _DatasetMatrix(features, target, sample_weight)


@dataclass(frozen=True, slots=True)
class _DatasetMatrix:
    features: FloatMatrix
    target: FloatVector
    sample_weight: FloatVector
