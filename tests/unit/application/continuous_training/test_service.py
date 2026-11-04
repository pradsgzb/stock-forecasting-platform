from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from stock_predictor.adapters.repositories.in_memory_model_registry import (
    InMemoryModelRegistryRepository,
)
from stock_predictor.adapters.repositories.in_memory_retraining_repository import (
    InMemoryRetrainingRepository,
)
from stock_predictor.application.continuous_training.service import (
    ContinuousTrainingService,
)
from stock_predictor.application.registry.service import ModelRegistryService
from stock_predictor.domain.common.errors import (
    ContinuousTrainingError,
    DomainConflictError,
)
from stock_predictor.domain.common.identifiers import (
    ModelVersionId,
    MonitoringAlertId,
)
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.mlops.continuous_training import (
    RetrainingStatus,
    RetrainingTrigger,
)
from stock_predictor.domain.mlops.feedback import FeedbackMetric, FeedbackSummary
from stock_predictor.domain.mlops.monitoring import MonitoringAlert, MonitoringSeverity
from stock_predictor.domain.mlops.registry import (
    ApprovalRole,
    ModelLifecycleState,
    PromotionPolicy,
    RegistryAlias,
)
from stock_predictor.domain.modeling.evaluation import MetricDirection
from tests.helpers.mlops import (
    DEFAULT_GATES,
    StubTrainingService,
    fixed_clock,
    promotion_evidence,
    scope,
    training_result,
)


def _services(now, *, result=None, error=None, automatic=False, minimum_outcomes=2):
    registry_repository = InMemoryModelRegistryRepository()
    registry = ModelRegistryService(
        registry_repository,
        fixed_clock(now),
        PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole)),
    )
    requests = InMemoryRetrainingRepository()
    training = StubTrainingService(result or training_result(now), error)
    service = ContinuousTrainingService(
        requests,
        training,
        registry,
        registry_repository,
        fixed_clock(now),
        minimum_outcomes=minimum_outcomes,
        minimum_improvement=Decimal("0.01"),
        allow_automatic_promotion=automatic,
    )
    return service, requests, training, registry, registry_repository


def _deploy(registry, result, now, *, promote: bool):
    candidate = registry.register_candidate(result, scope(), actor="trainer")
    validated, _ = registry.validate_candidate(
        candidate.model_version_id,
        promotion_evidence(now),
        actor="validator",
    )
    registry.stage(validated.model_version_id, actor="operator")
    registry.deploy_challenger(
        validated.model_version_id,
        actor="operator",
        reason="shadow evaluation",
    )
    if promote:
        registry.promote_challenger(
            validated.model_version_id,
            promotion_evidence(now),
            actor="approver",
            reason="approved",
        )
    return validated.model_version_id


def _summary(now, model_id, value: str, *, samples: int = 3):
    return FeedbackSummary(
        model_version_id=model_id,
        target_key=scope().target_key,
        window=InstantInterval(now.plus(-timedelta(days=1)), now),
        sample_count=samples,
        metrics=(FeedbackMetric("mae", value),),
        generated_at=now,
        outcome_fingerprints=tuple(f"{index + 1:064x}" for index in range(samples)),
    )


def test_retraining_request_is_idempotent_and_rejects_key_reuse(fixed_instant) -> None:
    service, _, _, _, _ = _services(fixed_instant)
    requested = service.request_retraining(
        scope=scope(),
        trigger=RetrainingTrigger.DATA_DRIFT,
        evidence_references=("drift:1",),
        requested_by="monitor",
        idempotency_key="retrain-1",
    )
    repeated = service.request_retraining(
        scope=scope(),
        trigger=RetrainingTrigger.DATA_DRIFT,
        evidence_references=("drift:1",),
        requested_by="monitor",
        idempotency_key="retrain-1",
    )
    assert repeated == requested
    with pytest.raises(DomainConflictError, match="reused"):
        service.request_retraining(
            scope=scope(),
            trigger=RetrainingTrigger.MANUAL,
            evidence_references=("manual:1",),
            requested_by="operator",
            idempotency_key="retrain-1",
        )


def test_continuous_training_run_registers_validated_challenger(fixed_instant) -> None:
    result = training_result(fixed_instant)
    service, requests, training, _, repository = _services(
        fixed_instant, result=result
    )
    request = service.request_retraining(
        scope=scope(),
        trigger=RetrainingTrigger.SCHEDULED,
        evidence_references=("schedule:daily",),
        requested_by="scheduler",
        idempotency_key="scheduled-1",
    )
    completed = service.run(
        request.request_id,
        object(),  # Stub training service deliberately ignores the concrete request.
        promotion_evidence(fixed_instant),
        actor="ml-operator",
    )
    assert completed.request.status is RetrainingStatus.SUCCEEDED
    assert completed.challenger_deployment is not None
    assert training.calls == 1
    assert service.current_result_model(request.request_id) == result.model_version_id
    assert repository.resolve_alias(scope(), RegistryAlias.CHALLENGER).model_version_id == (
        result.model_version_id
    )
    assert requests.get(request.request_id).revision == 3


def test_continuous_training_records_rejected_candidate_without_deployment(
    fixed_instant,
) -> None:
    service, _, _, _, repository = _services(fixed_instant)
    request = service.request_retraining(
        scope=scope(),
        trigger=RetrainingTrigger.MANUAL,
        evidence_references=("ticket:1",),
        requested_by="operator",
        idempotency_key="manual-1",
    )
    completed = service.run(
        request.request_id,
        object(),
        promotion_evidence(fixed_instant, passed=False),
        actor="operator",
    )
    assert completed.request.status is RetrainingStatus.SUCCEEDED
    assert not completed.promotion_decision.accepted
    assert completed.challenger_deployment is None
    assert repository.get(completed.training_result.model_version_id).state is (
        ModelLifecycleState.VALIDATION_FAILED
    )


def test_continuous_training_persists_terminal_failure(fixed_instant) -> None:
    service, requests, _, _, _ = _services(
        fixed_instant, error=RuntimeError("synthetic training failure")
    )
    request = service.request_retraining(
        scope=scope(),
        trigger=RetrainingTrigger.MANUAL,
        evidence_references=("ticket:2",),
        requested_by="operator",
        idempotency_key="manual-2",
    )
    with pytest.raises(ContinuousTrainingError, match="run failed"):
        service.run(
            request.request_id,
            object(),
            promotion_evidence(fixed_instant),
            actor="operator",
        )
    failed = requests.get(request.request_id)
    assert failed.status is RetrainingStatus.FAILED
    assert "synthetic training failure" in failed.failure_reason


def test_compare_requires_champion_and_challenger(fixed_instant) -> None:
    service, _, _, _, _ = _services(fixed_instant)
    model_a = ModelVersionId.new()
    model_b = ModelVersionId.new()
    with pytest.raises(ContinuousTrainingError, match="aliases"):
        service.compare_and_promote(
            scope=scope(),
            champion_summary=_summary(fixed_instant, model_a, "0.2"),
            challenger_summary=_summary(fixed_instant, model_b, "0.1"),
            metric_name="mae",
            direction=MetricDirection.MINIMIZE,
            promotion_evidence=promotion_evidence(fixed_instant),
            actor="approver",
            human_approved=True,
        )


def test_compare_human_gate_and_promote_challenger(fixed_instant) -> None:
    service, _, _, registry, repository = _services(fixed_instant)
    first = training_result(fixed_instant)
    champion_id = _deploy(registry, first, fixed_instant, promote=True)
    second = training_result(fixed_instant)
    challenger_id = _deploy(registry, second, fixed_instant, promote=False)
    champion_summary = _summary(fixed_instant, champion_id, "0.20")
    challenger_summary = _summary(fixed_instant, challenger_id, "0.10")

    comparison, deployment = service.compare_and_promote(
        scope=scope(),
        champion_summary=champion_summary,
        challenger_summary=challenger_summary,
        metric_name="mae",
        direction=MetricDirection.MINIMIZE,
        promotion_evidence=promotion_evidence(fixed_instant),
        actor="approver",
        human_approved=False,
    )
    assert comparison.accepted
    assert deployment is None
    assert repository.resolve_alias(scope(), RegistryAlias.CHAMPION).model_version_id == (
        champion_id
    )

    comparison, deployment = service.compare_and_promote(
        scope=scope(),
        champion_summary=champion_summary,
        challenger_summary=challenger_summary,
        metric_name="mae",
        direction=MetricDirection.MINIMIZE,
        promotion_evidence=promotion_evidence(fixed_instant),
        actor="approver",
        human_approved=True,
    )
    assert comparison.accepted
    assert deployment is not None
    assert repository.resolve_alias(scope(), RegistryAlias.CHAMPION).model_version_id == (
        challenger_id
    )


def test_compare_rejects_insufficient_improvement_and_wrong_feedback(fixed_instant) -> None:
    service, _, _, registry, _ = _services(fixed_instant, minimum_outcomes=4)
    champion_id = _deploy(
        registry, training_result(fixed_instant), fixed_instant, promote=True
    )
    challenger_id = _deploy(
        registry, training_result(fixed_instant), fixed_instant, promote=False
    )
    comparison, deployment = service.compare_and_promote(
        scope=scope(),
        champion_summary=_summary(fixed_instant, champion_id, "0.20", samples=3),
        challenger_summary=_summary(fixed_instant, challenger_id, "0.19", samples=3),
        metric_name="mae",
        direction=MetricDirection.MINIMIZE,
        promotion_evidence=promotion_evidence(fixed_instant),
        actor="approver",
        human_approved=True,
    )
    assert not comparison.accepted
    assert deployment is None
    with pytest.raises(ContinuousTrainingError, match="Champion feedback"):
        service.compare_and_promote(
            scope=scope(),
            champion_summary=_summary(fixed_instant, ModelVersionId.new(), "0.2"),
            challenger_summary=_summary(fixed_instant, challenger_id, "0.1"),
            metric_name="mae",
            direction=MetricDirection.MINIMIZE,
            promotion_evidence=promotion_evidence(fixed_instant),
            actor="approver",
            human_approved=True,
        )
    with pytest.raises(ContinuousTrainingError, match="Challenger feedback"):
        service.compare_and_promote(
            scope=scope(),
            champion_summary=_summary(fixed_instant, champion_id, "0.2"),
            challenger_summary=_summary(fixed_instant, ModelVersionId.new(), "0.1"),
            metric_name="mae",
            direction=MetricDirection.MINIMIZE,
            promotion_evidence=promotion_evidence(fixed_instant),
            actor="approver",
            human_approved=True,
        )


def test_automatic_promotion_policy_can_authorize(fixed_instant) -> None:
    service, _, _, registry, repository = _services(fixed_instant, automatic=True)
    champion_id = _deploy(
        registry, training_result(fixed_instant), fixed_instant, promote=True
    )
    challenger_id = _deploy(
        registry, training_result(fixed_instant), fixed_instant, promote=False
    )
    _, deployment = service.compare_and_promote(
        scope=scope(),
        champion_summary=_summary(fixed_instant, champion_id, "0.2"),
        challenger_summary=_summary(fixed_instant, challenger_id, "0.1"),
        metric_name="mae",
        direction=MetricDirection.MINIMIZE,
        promotion_evidence=promotion_evidence(fixed_instant),
        actor="policy-engine",
        human_approved=False,
    )
    assert deployment is not None
    assert repository.resolve_alias(scope(), RegistryAlias.CHAMPION).model_version_id == (
        challenger_id
    )


def test_critical_alert_rolls_back_current_champion(fixed_instant) -> None:
    service, _, _, registry, repository = _services(fixed_instant)
    first_id = _deploy(
        registry, training_result(fixed_instant), fixed_instant, promote=True
    )
    second_id = _deploy(
        registry, training_result(fixed_instant), fixed_instant, promote=False
    )
    registry.promote_challenger(
        second_id,
        promotion_evidence(fixed_instant),
        actor="approver",
        reason="second champion",
    )
    alert = MonitoringAlert(
        alert_id=MonitoringAlertId.new(),
        model_version_id=second_id,
        severity=MonitoringSeverity.CRITICAL,
        category="performance_degradation",
        title="Critical performance degradation",
        detail="Rollback threshold crossed.",
        evidence_reference="snapshot:critical",
        raised_at=fixed_instant,
    )
    deployment = service.rollback_on_alert(scope(), alert, actor="incident-commander")
    assert deployment.model_version_id == first_id
    assert repository.resolve_alias(scope(), RegistryAlias.CHAMPION).model_version_id == (
        first_id
    )
    assert repository.get(second_id).state is ModelLifecycleState.ROLLED_BACK


def test_rollback_rejects_noncritical_or_unrelated_alert(fixed_instant) -> None:
    service, _, _, registry, _ = _services(fixed_instant)
    champion_id = _deploy(
        registry, training_result(fixed_instant), fixed_instant, promote=True
    )
    warning = MonitoringAlert(
        MonitoringAlertId.new(),
        champion_id,
        MonitoringSeverity.WARNING,
        "performance_degradation",
        "Warning",
        "Review required.",
        "snapshot:warning",
        fixed_instant,
    )
    with pytest.raises(ContinuousTrainingError, match="critical"):
        service.rollback_on_alert(scope(), warning, actor="operator")
    unrelated = MonitoringAlert(
        MonitoringAlertId.new(),
        ModelVersionId.new(),
        MonitoringSeverity.CRITICAL,
        "performance_degradation",
        "Critical",
        "Review required.",
        "snapshot:other",
        fixed_instant,
    )
    with pytest.raises(ContinuousTrainingError, match="current champion"):
        service.rollback_on_alert(scope(), unrelated, actor="operator")


def test_continuous_training_configuration_validation(fixed_instant) -> None:
    repository = InMemoryModelRegistryRepository()
    registry = ModelRegistryService(
        repository,
        fixed_clock(fixed_instant),
        PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole)),
    )
    with pytest.raises(ContinuousTrainingError, match="thresholds"):
        ContinuousTrainingService(
            InMemoryRetrainingRepository(),
            StubTrainingService(training_result(fixed_instant)),
            registry,
            repository,
            fixed_clock(fixed_instant),
            minimum_outcomes=0,
        )
