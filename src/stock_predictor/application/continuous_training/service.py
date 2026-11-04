"""Controlled retraining, challenger deployment, promotion, and rollback workflows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from stock_predictor.application.registry.service import ModelRegistryService
from stock_predictor.application.training.service import TrainingRequest
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import (
    ContinuousTrainingError,
    DomainConflictError,
)
from stock_predictor.domain.common.identifiers import ModelVersionId, RetrainingRequestId
from stock_predictor.domain.mlops.continuous_training import (
    ChampionChallengerComparison,
    RetrainingRequest,
    RetrainingStatus,
    RetrainingTrigger,
)
from stock_predictor.domain.mlops.feedback import FeedbackSummary
from stock_predictor.domain.mlops.monitoring import MonitoringAlert, MonitoringSeverity
from stock_predictor.domain.mlops.registry import (
    ModelDeployment,
    ModelDeploymentScope,
    PromotionDecision,
    PromotionEvidence,
    RegistryAlias,
)
from stock_predictor.domain.modeling.evaluation import MetricDirection
from stock_predictor.domain.modeling.training import TrainingResult
from stock_predictor.ports.model_registry import ModelRegistryRepository
from stock_predictor.ports.retraining_repository import RetrainingRepository


class TrainingExecutor(Protocol):
    """Narrow port required by controlled continuous training."""

    def train(self, request: TrainingRequest) -> TrainingResult:
        ...


@dataclass(frozen=True, slots=True)
class ContinuousTrainingResult:
    request: RetrainingRequest
    training_result: TrainingResult
    promotion_decision: PromotionDecision
    challenger_deployment: ModelDeployment | None


class ContinuousTrainingService:
    __slots__ = (
        "_allow_automatic_promotion",
        "_clock",
        "_minimum_improvement",
        "_minimum_outcomes",
        "_registry",
        "_registry_repository",
        "_requests",
        "_training",
    )

    def __init__(
        self,
        requests: RetrainingRepository,
        training: TrainingExecutor,
        registry: ModelRegistryService,
        registry_repository: ModelRegistryRepository,
        clock: Clock,
        *,
        minimum_outcomes: int = 30,
        minimum_improvement: Decimal = Decimal("0.01"),
        allow_automatic_promotion: bool = False,
    ) -> None:
        if minimum_outcomes <= 0 or minimum_improvement < 0:
            raise ContinuousTrainingError("Continuous-training thresholds are invalid")
        self._requests = requests
        self._training = training
        self._registry = registry
        self._registry_repository = registry_repository
        self._clock = clock
        self._minimum_outcomes = minimum_outcomes
        self._minimum_improvement = minimum_improvement
        self._allow_automatic_promotion = allow_automatic_promotion

    def request_retraining(
        self,
        *,
        scope: ModelDeploymentScope,
        trigger: RetrainingTrigger,
        evidence_references: tuple[str, ...],
        requested_by: str,
        idempotency_key: str,
    ) -> RetrainingRequest:
        existing = self._requests.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            identity = (
                existing.scope,
                existing.trigger,
                existing.evidence_references,
                existing.requested_by,
            )
            requested = (
                scope,
                trigger,
                tuple(item.strip() for item in evidence_references if item.strip()),
                requested_by.strip(),
            )
            if identity != requested:
                raise DomainConflictError(
                    "Retraining idempotency key was reused for a different request"
                )
            return existing
        now = self._clock.now()
        request = RetrainingRequest(
            request_id=RetrainingRequestId.new(),
            idempotency_key=idempotency_key,
            scope=scope,
            trigger=trigger,
            evidence_references=evidence_references,
            requested_by=requested_by,
            requested_at=now,
            status=RetrainingStatus.PENDING,
            revision=1,
            updated_at=now,
        )
        self._requests.add(request)
        return request

    def run(
        self,
        request_id: RetrainingRequestId,
        training_request: TrainingRequest,
        validation_evidence: PromotionEvidence,
        *,
        actor: str,
    ) -> ContinuousTrainingResult:
        request = self._requests.get(request_id)
        running = request.transition(RetrainingStatus.RUNNING, self._clock.now())
        self._requests.save(running, expected_revision=request.revision)
        try:
            training_result = self._training.train(training_request)
            candidate = self._registry.register_candidate(
                training_result,
                running.scope,
                actor=actor,
            )
            validated, decision = self._registry.validate_candidate(
                candidate.model_version_id,
                validation_evidence,
                actor=actor,
            )
            deployment = None
            if decision.accepted:
                staged = self._registry.stage(validated.model_version_id, actor=actor)
                deployment = self._registry.deploy_challenger(
                    staged.model_version_id,
                    actor=actor,
                    reason="continuous-training candidate passed validation",
                )
            succeeded = running.transition(
                RetrainingStatus.SUCCEEDED,
                self._clock.now(),
                result_model_version_id=training_result.model_version_id,
            )
            self._requests.save(succeeded, expected_revision=running.revision)
            return ContinuousTrainingResult(
                succeeded,
                training_result,
                decision,
                deployment,
            )
        except Exception as exc:  # noqa: BLE001 - persist terminal orchestration failure
            failed = running.transition(
                RetrainingStatus.FAILED,
                self._clock.now(),
                failure_reason=str(exc)[:500],
            )
            self._requests.save(failed, expected_revision=running.revision)
            raise ContinuousTrainingError("Continuous-training run failed") from exc

    def compare_and_promote(
        self,
        *,
        scope: ModelDeploymentScope,
        champion_summary: FeedbackSummary,
        challenger_summary: FeedbackSummary,
        metric_name: str,
        direction: MetricDirection,
        promotion_evidence: PromotionEvidence,
        actor: str,
        human_approved: bool,
    ) -> tuple[ChampionChallengerComparison, ModelDeployment | None]:
        champion = self._registry_repository.resolve_alias(scope, RegistryAlias.CHAMPION)
        challenger = self._registry_repository.resolve_alias(
            scope, RegistryAlias.CHALLENGER
        )
        if champion is None or challenger is None:
            raise ContinuousTrainingError("Champion and challenger aliases are required")
        if champion_summary.model_version_id != champion.model_version_id:
            raise ContinuousTrainingError("Champion feedback belongs to another model")
        if challenger_summary.model_version_id != challenger.model_version_id:
            raise ContinuousTrainingError("Challenger feedback belongs to another model")
        comparison = ChampionChallengerComparison(
            champion_model_version_id=champion.model_version_id,
            challenger_model_version_id=challenger.model_version_id,
            metric_name=metric_name,
            direction=direction,
            champion_value=champion_summary.metric(metric_name).value,
            challenger_value=challenger_summary.metric(metric_name).value,
            minimum_improvement=self._minimum_improvement,
            champion_sample_count=champion_summary.sample_count,
            challenger_sample_count=challenger_summary.sample_count,
            minimum_sample_count=self._minimum_outcomes,
            compared_at=self._clock.now(),
        )
        authorized = human_approved or self._allow_automatic_promotion
        if not comparison.accepted or not authorized:
            return comparison, None
        deployment, _ = self._registry.promote_challenger(
            challenger.model_version_id,
            promotion_evidence,
            actor=actor,
            reason=(
                f"challenger improved {comparison.metric_name} by "
                f"{comparison.improvement} with sufficient outcomes"
            ),
        )
        return comparison, deployment

    def rollback_on_alert(
        self,
        scope: ModelDeploymentScope,
        alert: MonitoringAlert,
        *,
        actor: str,
    ) -> ModelDeployment:
        if alert.severity is not MonitoringSeverity.CRITICAL:
            raise ContinuousTrainingError("Only critical monitoring alerts permit rollback")
        champion = self._registry_repository.resolve_alias(scope, RegistryAlias.CHAMPION)
        if champion is None or champion.model_version_id != alert.model_version_id:
            raise ContinuousTrainingError("Alert does not refer to the current champion")
        return self._registry.rollback(
            scope,
            actor=actor,
            reason=alert.detail,
            evidence_references=(alert.evidence_reference,),
        )

    def current_result_model(
        self, request_id: RetrainingRequestId
    ) -> ModelVersionId | None:
        return self._requests.get(request_id).result_model_version_id
