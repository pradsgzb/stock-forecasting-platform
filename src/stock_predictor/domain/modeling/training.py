"""Immutable evidence emitted by model-selection and training pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import ExperimentRunId, ModelVersionId
from stock_predictor.domain.modeling.evaluation import EvaluationReport, MetricDirection
from stock_predictor.domain.modeling.models import ModelArtifact, ModelCard, ModelSpec


class TrialStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TrialSummary:
    trial_number: int
    spec: ModelSpec
    status: TrialStatus
    fold_scores: tuple[Decimal, ...]
    mean_score: Decimal | None
    metric_name: str
    metric_direction: MetricDirection
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.trial_number <= 0 or not self.metric_name.strip():
            raise DomainValidationError("Trial number and metric are required")
        if self.status is TrialStatus.COMPLETED:
            if not self.fold_scores or self.mean_score is None or self.failure_reason is not None:
                raise DomainValidationError("Completed trials require scores and no failure")
        elif self.fold_scores or self.mean_score is not None or not self.failure_reason:
            raise DomainValidationError("Failed trials require only a failure reason")


@dataclass(frozen=True, slots=True)
class TrainingResult:
    run_id: ExperimentRunId
    model_version_id: ModelVersionId
    selected_spec: ModelSpec
    primary_metric: str
    cross_validation_score: Decimal
    holdout_report: EvaluationReport
    artifact: ModelArtifact
    model_card: ModelCard
    trials: tuple[TrialSummary, ...]

    def __post_init__(self) -> None:
        if not self.primary_metric.strip() or not self.trials:
            raise DomainValidationError("Training result requires metric and trial evidence")
        if self.artifact.model_version_id != self.model_version_id:
            raise DomainValidationError("Training result artifact has a different model version")
        if self.model_card.model_version_id != self.model_version_id:
            raise DomainValidationError("Training result model card has a different version")
        if self.selected_spec != self.artifact.spec:
            raise DomainValidationError("Selected spec differs from artifact spec")
