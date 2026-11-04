from __future__ import annotations

import pytest

from stock_predictor.adapters.repositories.in_memory_model_registry import (
    InMemoryModelRegistryRepository,
)
from stock_predictor.application.registry.service import ModelRegistryService
from stock_predictor.domain.common.errors import ModelRegistryError
from stock_predictor.domain.mlops.registry import (
    ApprovalRole,
    DeploymentMode,
    ModelLifecycleState,
    PromotionPolicy,
)
from tests.helpers.mlops import (
    DEFAULT_GATES,
    fixed_clock,
    promotion_evidence,
    scope,
    training_result,
)


def _service(fixed_instant):
    repository = InMemoryModelRegistryRepository()
    service = ModelRegistryService(
        repository,
        fixed_clock(fixed_instant),
        PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole)),
    )
    return repository, service


def test_service_rejects_active_challenger_deployment(fixed_instant) -> None:
    _, service = _service(fixed_instant)
    result = training_result(fixed_instant)
    candidate = service.register_candidate(result, scope(), actor="trainer")
    validated, _ = service.validate_candidate(
        candidate.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    staged = service.stage(validated.model_version_id, actor="operator")
    with pytest.raises(ModelRegistryError, match="shadow or canary"):
        service.deploy_challenger(
            staged.model_version_id,
            actor="operator",
            reason="bad",
            mode=DeploymentMode.ACTIVE,
        )


def test_service_rejects_unassigned_promotion_and_missing_rollback(fixed_instant) -> None:
    repository, service = _service(fixed_instant)
    result = training_result(fixed_instant)
    candidate = service.register_candidate(result, scope(), actor="trainer")
    validated, _ = service.validate_candidate(
        candidate.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    staged = service.stage(validated.model_version_id, actor="operator")
    with pytest.raises(ModelRegistryError, match="assigned challenger"):
        service.promote_challenger(
            staged.model_version_id,
            promotion_evidence(fixed_instant),
            actor="approver",
            reason="skip deployment",
        )
    with pytest.raises(ModelRegistryError, match="No champion"):
        service.rollback(scope(), actor="operator", reason="none")
    assert repository.get(staged.model_version_id).state is ModelLifecycleState.STAGING


def test_service_rejects_failed_promotion_evidence(fixed_instant) -> None:
    _, service = _service(fixed_instant)
    result = training_result(fixed_instant)
    candidate = service.register_candidate(result, scope(), actor="trainer")
    validated, _ = service.validate_candidate(
        candidate.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    staged = service.stage(validated.model_version_id, actor="operator")
    service.deploy_challenger(staged.model_version_id, actor="operator", reason="shadow")
    with pytest.raises(ModelRegistryError, match="rejected"):
        service.promote_challenger(
            staged.model_version_id,
            promotion_evidence(fixed_instant, passed=False),
            actor="approver",
            reason="bad evidence",
        )
