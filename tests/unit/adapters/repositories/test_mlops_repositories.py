from __future__ import annotations

from datetime import timedelta

import pytest

from stock_predictor.adapters.repositories.in_memory_model_registry import (
    InMemoryModelRegistryRepository,
)
from stock_predictor.adapters.repositories.in_memory_monitoring_repository import (
    InMemoryMonitoringRepository,
)
from stock_predictor.adapters.repositories.in_memory_outcome_repository import (
    InMemoryOutcomeRepository,
)
from stock_predictor.adapters.repositories.in_memory_prediction_ledger import (
    InMemoryPredictionLedger,
)
from stock_predictor.adapters.repositories.in_memory_retraining_repository import (
    InMemoryRetrainingRepository,
)
from stock_predictor.application.registry.service import ModelRegistryService
from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    ImmutableObjectConflictError,
)
from stock_predictor.domain.common.identifiers import (
    DriftReportId,
    LabelId,
    MonitoringAlertId,
    OutcomeId,
    PredictionId,
    RetrainingRequestId,
)
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.mlops.continuous_training import (
    RetrainingRequest,
    RetrainingStatus,
    RetrainingTrigger,
)
from stock_predictor.domain.mlops.feedback import RealizedOutcome
from stock_predictor.domain.mlops.inference import PredictionBatch
from stock_predictor.domain.mlops.monitoring import (
    DriftKind,
    DriftMeasure,
    DriftReport,
    MonitoringAlert,
    MonitoringSeverity,
)
from stock_predictor.domain.mlops.registry import (
    ApprovalRole,
    ModelLifecycleState,
    PromotionPolicy,
    RegistryAlias,
    RegistryMutation,
    RegistryRelease,
)
from tests.helpers.mlops import (
    DEFAULT_GATES,
    fixed_clock,
    promotion_evidence,
    scope,
    training_result,
)
from tests.unit.domain.mlops.test_inference_feedback_monitoring import _prediction


def _registry(fixed_instant):
    repository = InMemoryModelRegistryRepository()
    service = ModelRegistryService(
        repository,
        fixed_clock(fixed_instant),
        PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole)),
    )
    return repository, service


def test_registry_repository_and_service_full_lifecycle(fixed_instant) -> None:
    repository, service = _registry(fixed_instant)
    result = training_result(fixed_instant)
    model_scope = scope()
    candidate = service.register_candidate(result, model_scope, actor="trainer")
    validated, decision = service.validate_candidate(
        candidate.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    assert decision.accepted
    staged = service.stage(validated.model_version_id, actor="release-manager")
    shadow = service.deploy_challenger(
        staged.model_version_id,
        actor="release-manager",
        reason="shadow evaluation",
    )
    assert shadow.model_version_id == staged.model_version_id
    assert repository.resolve_alias(model_scope, RegistryAlias.CHALLENGER) == repository.get(
        staged.model_version_id
    )
    active, _ = service.promote_challenger(
        staged.model_version_id,
        promotion_evidence(fixed_instant),
        actor="deployment-approver",
        reason="approved initial champion",
    )
    assert active.model_version_id == staged.model_version_id
    assert repository.resolve_alias(model_scope, RegistryAlias.CHAMPION).state is (
        ModelLifecycleState.CHAMPION
    )
    assert len(repository.history(staged.model_version_id)) == 5


def test_registry_service_promotes_second_model_and_rolls_back(fixed_instant) -> None:
    repository, service = _registry(fixed_instant)
    model_scope = scope()
    first = training_result(fixed_instant)
    first_candidate = service.register_candidate(first, model_scope, actor="trainer")
    first_validated, _ = service.validate_candidate(
        first_candidate.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    service.stage(first_validated.model_version_id, actor="operator")
    service.deploy_challenger(
        first_validated.model_version_id,
        actor="operator",
        reason="initial shadow",
    )
    service.promote_challenger(
        first_validated.model_version_id,
        promotion_evidence(fixed_instant),
        actor="approver",
        reason="initial promotion",
    )
    second = training_result(fixed_instant)
    second_candidate = service.register_candidate(second, model_scope, actor="trainer")
    second_validated, _ = service.validate_candidate(
        second_candidate.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    service.stage(second_validated.model_version_id, actor="operator")
    service.deploy_challenger(
        second_validated.model_version_id,
        actor="operator",
        reason="second shadow",
    )
    service.promote_challenger(
        second_validated.model_version_id,
        promotion_evidence(fixed_instant),
        actor="approver",
        reason="second promotion",
    )
    assert repository.resolve_alias(model_scope, RegistryAlias.CHAMPION).model_version_id == (
        second.model_version_id
    )
    rollback = service.rollback(
        model_scope,
        actor="incident-commander",
        reason="critical degradation",
        evidence_references=("alert:critical",),
    )
    assert rollback.model_version_id == first.model_version_id
    assert repository.resolve_alias(model_scope, RegistryAlias.CHAMPION).model_version_id == (
        first.model_version_id
    )
    assert repository.get(second.model_version_id).state is ModelLifecycleState.ROLLED_BACK


def test_registry_rejected_validation_and_challenger_replacement(fixed_instant) -> None:
    repository, service = _registry(fixed_instant)
    model_scope = scope()
    rejected = service.register_candidate(
        training_result(fixed_instant), model_scope, actor="trainer"
    )
    failed, decision = service.validate_candidate(
        rejected.model_version_id,
        promotion_evidence(fixed_instant, passed=False),
        actor="validator",
    )
    assert not decision.accepted
    assert failed.state is ModelLifecycleState.VALIDATION_FAILED

    first = service.register_candidate(
        training_result(fixed_instant), model_scope, actor="trainer"
    )
    first, _ = service.validate_candidate(
        first.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    service.stage(first.model_version_id, actor="operator")
    service.deploy_challenger(first.model_version_id, actor="operator", reason="first")
    second = service.register_candidate(
        training_result(fixed_instant), model_scope, actor="trainer"
    )
    second, _ = service.validate_candidate(
        second.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    service.stage(second.model_version_id, actor="operator")
    service.deploy_challenger(second.model_version_id, actor="operator", reason="replace")
    assert repository.get(first.model_version_id).state is ModelLifecycleState.RETIRED
    assert repository.resolve_alias(model_scope, RegistryAlias.CHALLENGER).model_version_id == (
        second.model_version_id
    )


def test_registry_repository_detects_stale_revision(fixed_instant) -> None:
    repository, service = _registry(fixed_instant)
    candidate = service.register_candidate(
        training_result(fixed_instant), scope(), actor="trainer"
    )
    updated, transition = candidate.transition(
        ModelLifecycleState.VALIDATED,
        actor="validator",
        reason="ok",
        occurred_at=fixed_instant,
    )
    mutation = RegistryMutation(updated, transition, candidate.revision)
    repository.commit_release(RegistryRelease((mutation,)))
    with pytest.raises(DomainConflictError, match="revision"):
        repository.commit_release(RegistryRelease((mutation,)))
    with pytest.raises(DomainNotFoundError):
        repository.get(training_result(fixed_instant).model_version_id)


def _batch(fixed_instant) -> PredictionBatch:
    from stock_predictor.domain.mlops.inference import PredictionBatchStatus

    prediction = _prediction(fixed_instant)
    return PredictionBatch(
        prediction.batch_id,
        "ledger-key",
        "e" * 64,
        prediction.scope,
        prediction.model_version_id,
        "f" * 64,
        "1" * 64,
        fixed_instant,
        fixed_instant,
        PredictionBatchStatus.COMPLETED,
        (prediction,),
        (),
    )


def test_prediction_ledger_is_idempotent_and_supports_correction(fixed_instant) -> None:
    ledger = InMemoryPredictionLedger()
    batch = _batch(fixed_instant)
    ledger.append_batch(batch)
    ledger.append_batch(batch)
    assert ledger.get_batch_by_idempotency_key("ledger-key") == batch
    original = batch.predictions[0]
    corrected = _prediction(fixed_instant, correction_of=original.prediction_id)
    values = corrected.__dict__ if hasattr(corrected, "__dict__") else None
    del values
    # Rebuild with the immutable business identity of the original.
    from stock_predictor.domain.mlops.inference import PredictionRecord

    corrected = PredictionRecord(
        prediction_id=corrected.prediction_id,
        batch_id=corrected.batch_id,
        scope=original.scope,
        instrument_id=original.instrument_id,
        as_of=original.as_of,
        decision_cutoff=original.decision_cutoff,
        generated_at=original.generated_at,
        horizon=original.horizon,
        model_version_id=original.model_version_id,
        artifact_sha256=original.artifact_sha256,
        signature_fingerprint=original.signature_fingerprint,
        feature_snapshot_id=original.feature_snapshot_id,
        feature_snapshot_fingerprint=original.feature_snapshot_fingerprint,
        input_fingerprint=original.input_fingerprint,
        predicted_value="0.12",
        correction_of=original.prediction_id,
    )
    ledger.append_correction(original.prediction_id, corrected)
    assert ledger.list_predictions() == (corrected,)
    assert len(ledger.list_predictions(latest_only=False)) == 2
    with pytest.raises(DomainConflictError):
        ledger.append_correction(original.prediction_id, corrected)


def test_prediction_ledger_rejects_conflicting_idempotency(fixed_instant) -> None:
    ledger = InMemoryPredictionLedger()
    batch = _batch(fixed_instant)
    ledger.append_batch(batch)
    another = _batch(fixed_instant)
    from dataclasses import replace

    another = replace(another, idempotency_key=batch.idempotency_key)
    with pytest.raises(ImmutableObjectConflictError):
        ledger.append_batch(another)
    with pytest.raises(DomainNotFoundError):
        ledger.get_prediction(PredictionId.new())


def test_outcome_repository_enforces_revision_chain(fixed_instant) -> None:
    repository = InMemoryOutcomeRepository()
    prediction = _prediction(fixed_instant)
    first = RealizedOutcome(
        outcome_id=OutcomeId.new(),
        prediction_id=prediction.prediction_id,
        model_version_id=prediction.model_version_id,
        instrument_id=prediction.instrument_id,
        target_key=prediction.scope.target_key,
        as_of=prediction.as_of,
        horizon_end=prediction.as_of + timedelta(days=1),
        observed_at=fixed_instant,
        source_label_id=LabelId.new(),
        source_label_fingerprint="a" * 64,
        prediction_value="0.1",
        actual_value="0.2",
        positive_probability=None,
        direction_correct=True,
        revision=1,
    )
    repository.append(first)
    repository.append(first)
    second = RealizedOutcome(
        outcome_id=OutcomeId.new(),
        prediction_id=prediction.prediction_id,
        model_version_id=prediction.model_version_id,
        instrument_id=prediction.instrument_id,
        target_key=prediction.scope.target_key,
        as_of=prediction.as_of,
        horizon_end=prediction.as_of + timedelta(days=1),
        observed_at=fixed_instant,
        source_label_id=LabelId.new(),
        source_label_fingerprint="b" * 64,
        prediction_value="0.1",
        actual_value="0.3",
        positive_probability=None,
        direction_correct=True,
        revision=2,
        supersedes=first.outcome_id,
    )
    repository.append(second)
    assert repository.latest_for_prediction(prediction.prediction_id) == second
    assert repository.history(prediction.prediction_id) == (first, second)


def test_monitoring_and_retraining_repositories(fixed_instant) -> None:
    monitoring = InMemoryMonitoringRepository()
    reference = InstantInterval(
        fixed_instant.plus(-timedelta(hours=2)),
        fixed_instant.plus(-timedelta(hours=1)),
    )
    current = InstantInterval(
        fixed_instant.plus(-timedelta(hours=1)), fixed_instant
    )
    model_id = training_result(fixed_instant).model_version_id
    report = DriftReport(
        DriftReportId.new(),
        model_id,
        DriftKind.FEATURE,
        "momentum",
        reference,
        current,
        30,
        30,
        (DriftMeasure("psi", "0.2", "0.1", "0.25"),),
        fixed_instant,
    )
    monitoring.append_drift_report(report)
    monitoring.append_drift_report(report)
    alert = MonitoringAlert(
        MonitoringAlertId.new(),
        model_id,
        MonitoringSeverity.WARNING,
        "feature_drift",
        "Drift",
        "Review",
        report.fingerprint,
        fixed_instant,
    )
    monitoring.append_alert(alert)
    assert monitoring.drift_reports(model_version_id=model_id) == (report,)
    assert monitoring.alerts(model_version_id=model_id) == (alert,)

    retraining = InMemoryRetrainingRepository()
    request = RetrainingRequest(
        RetrainingRequestId.new(),
        "request-key",
        scope(),
        RetrainingTrigger.MANUAL,
        (),
        "operator",
        fixed_instant,
        RetrainingStatus.PENDING,
        1,
        fixed_instant,
    )
    retraining.add(request)
    retraining.add(request)
    running = request.transition(RetrainingStatus.RUNNING, fixed_instant)
    retraining.save(running, expected_revision=1)
    assert retraining.get(request.request_id) == running
    with pytest.raises(DomainConflictError):
        retraining.save(running, expected_revision=1)
