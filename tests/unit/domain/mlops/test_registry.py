from __future__ import annotations

from datetime import timedelta

import pytest

from stock_predictor.domain.common.errors import DomainValidationError, ModelRegistryError
from stock_predictor.domain.common.identifiers import (
    ModelDeploymentId,
    RegistryTransitionId,
)
from stock_predictor.domain.mlops.registry import (
    AliasBinding,
    AliasMutation,
    ApprovalDecision,
    ApprovalRole,
    DeploymentMode,
    DeploymentStatus,
    GateResult,
    LifecycleTransition,
    ModelApproval,
    ModelDeployment,
    ModelDeploymentScope,
    ModelLifecycleState,
    PromotionEvidence,
    PromotionPolicy,
    RegisteredModelVersion,
    RegistryAlias,
    RegistryMutation,
    RegistryRelease,
)
from stock_predictor.domain.modeling.models import LearningTask
from tests.helpers.mlops import DEFAULT_GATES, promotion_evidence, scope, training_result


def _record(fixed_instant):
    result = training_result(fixed_instant)
    model_scope = scope()
    return RegisteredModelVersion(
        result.model_version_id,
        result.run_id,
        model_scope,
        result.artifact,
        result.model_card,
        ModelLifecycleState.CANDIDATE,
        1,
        fixed_instant,
        fixed_instant,
    )


def test_scope_is_normalized_and_fingerprinted() -> None:
    model_scope = ModelDeploymentScope(
        " Staging ",
        " Future_Return@1.0.0 ",
        LearningTask.REGRESSION,
    )
    assert model_scope.environment == "staging"
    assert model_scope.target_key == "future_return@1.0.0"
    assert len(model_scope.fingerprint) == 64


@pytest.mark.parametrize(
    "environment,target",
    [("", "target"), ("bad value", "target"), ("prod", "")],
)
def test_scope_rejects_invalid_identity(environment, target) -> None:
    with pytest.raises(DomainValidationError):
        ModelDeploymentScope(environment, target, LearningTask.REGRESSION)


def test_registered_model_enforces_scope_signature(fixed_instant) -> None:
    result = training_result(fixed_instant)
    wrong = ModelDeploymentScope(
        "staging", "another@1.0.0", LearningTask.REGRESSION
    )
    with pytest.raises(DomainValidationError, match="target"):
        RegisteredModelVersion(
            result.model_version_id,
            result.run_id,
            wrong,
            result.artifact,
            result.model_card,
            ModelLifecycleState.CANDIDATE,
            1,
            fixed_instant,
            fixed_instant,
        )


def test_lifecycle_transition_is_immutable_and_sequenced(fixed_instant) -> None:
    record = _record(fixed_instant)
    updated, transition = record.transition(
        ModelLifecycleState.VALIDATED,
        actor="validator",
        reason="passed gates",
        occurred_at=fixed_instant,
        evidence_references=("evidence:1",),
    )
    assert record.state is ModelLifecycleState.CANDIDATE
    assert updated.state is ModelLifecycleState.VALIDATED
    assert updated.revision == 2
    assert transition.previous_state is ModelLifecycleState.CANDIDATE
    assert transition.sequence == 2
    assert len(transition.fingerprint) == 64


def test_lifecycle_rejects_illegal_and_backward_transition(fixed_instant) -> None:
    record = _record(fixed_instant)
    with pytest.raises(ModelRegistryError, match="Illegal"):
        record.transition(
            ModelLifecycleState.CHAMPION,
            actor="operator",
            reason="skip controls",
            occurred_at=fixed_instant,
        )
    with pytest.raises(ModelRegistryError, match="backward"):
        record.transition(
            ModelLifecycleState.VALIDATED,
            actor="operator",
            reason="old event",
            occurred_at=fixed_instant.plus(-timedelta(seconds=1)),
        )


def test_promotion_policy_accepts_complete_approved_evidence(fixed_instant) -> None:
    policy = PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole))
    decision = policy.evaluate(promotion_evidence(fixed_instant), fixed_instant)
    assert decision.accepted
    assert decision.reasons == ()


def test_promotion_policy_reports_failed_gate_and_missing_approval(fixed_instant) -> None:
    policy = PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole))
    evidence = PromotionEvidence(
        (
            GateResult("artifact_verified", False, "evidence:a", "failed"),
        ),
        (
            ModelApproval(
                "risk",
                ApprovalRole.RISK_OWNER,
                ApprovalDecision.REJECTED,
                fixed_instant,
                "risk failed",
            ),
        ),
        fixed_instant,
    )
    decision = policy.evaluate(evidence, fixed_instant)
    assert not decision.accepted
    assert any("gate failed" in item for item in decision.reasons)
    assert any("missing" in item for item in decision.reasons)
    assert any("rejected" in item for item in decision.reasons)


def test_promotion_evidence_rejects_duplicate_gates_and_approvals(fixed_instant) -> None:
    gate = GateResult("artifact_verified", True, "e:a", "ok")
    with pytest.raises(DomainValidationError, match="unique gates"):
        PromotionEvidence((gate, gate), (), fixed_instant)
    approval = ModelApproval(
        "reviewer",
        ApprovalRole.RISK_OWNER,
        ApprovalDecision.APPROVED,
        fixed_instant,
        "ok",
    )
    with pytest.raises(DomainValidationError, match="unique by actor"):
        PromotionEvidence((gate,), (approval, approval), fixed_instant)


def test_model_deployment_can_be_ended_once(fixed_instant) -> None:
    model_id = training_result(fixed_instant).model_version_id
    deployment = ModelDeployment(
        ModelDeploymentId.new(),
        scope(),
        model_id,
        DeploymentMode.SHADOW,
        DeploymentStatus.ACTIVE,
        fixed_instant,
        None,
        None,
        "shadow test",
    )
    ended = deployment.end(
        DeploymentStatus.SUPERSEDED,
        fixed_instant.plus(timedelta(minutes=1)),
        "replaced",
    )
    assert ended.status is DeploymentStatus.SUPERSEDED
    with pytest.raises(ModelRegistryError):
        ended.end(DeploymentStatus.RETIRED, ended.ended_at, "again")


def test_registry_release_validates_revision_and_duplicates(fixed_instant) -> None:
    record = _record(fixed_instant)
    updated, transition = record.transition(
        ModelLifecycleState.VALIDATED,
        actor="validator",
        reason="ok",
        occurred_at=fixed_instant,
    )
    mutation = RegistryMutation(updated, transition, 1)
    release = RegistryRelease((mutation,))
    assert release.mutations == (mutation,)
    with pytest.raises(DomainValidationError, match="mutate a model twice"):
        RegistryRelease((mutation, mutation))
    alias = AliasMutation(
        AliasBinding(scope(), RegistryAlias.CHAMPION, updated.model_version_id, fixed_instant),
        None,
    )
    with pytest.raises(DomainValidationError, match="aliases"):
        RegistryRelease((mutation,), (alias, alias))


def test_transition_validates_required_fields(fixed_instant) -> None:
    with pytest.raises(DomainValidationError):
        LifecycleTransition(
            RegistryTransitionId.new(),
            training_result(fixed_instant).model_version_id,
            0,
            None,
            ModelLifecycleState.CANDIDATE,
            "",
            "",
            fixed_instant,
        )
