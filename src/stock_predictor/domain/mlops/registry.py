"""Governed model registry, lifecycle, approvals, aliases, and deployments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError, ModelRegistryError
from stock_predictor.domain.common.identifiers import (
    ExperimentRunId,
    ModelDeploymentId,
    ModelVersionId,
    RegistryTransitionId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelArtifact,
    ModelCard,
)

_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")


class ModelLifecycleState(StrEnum):
    EXPERIMENTAL = "experimental"
    CANDIDATE = "candidate"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"
    STAGING = "staging"
    CHALLENGER = "challenger"
    CHAMPION = "champion"
    DEGRADED = "degraded"
    ROLLED_BACK = "rolled_back"
    RETIRED = "retired"
    ARCHIVED = "archived"


class RegistryAlias(StrEnum):
    CHAMPION = "champion"
    CHALLENGER = "challenger"


class DeploymentMode(StrEnum):
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"


class DeploymentStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    RETIRED = "retired"


class ApprovalRole(StrEnum):
    MODEL_VALIDATOR = "model_validator"
    RISK_OWNER = "risk_owner"
    DEPLOYMENT_APPROVER = "deployment_approver"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


_ALLOWED_TRANSITIONS: dict[ModelLifecycleState, frozenset[ModelLifecycleState]] = {
    ModelLifecycleState.EXPERIMENTAL: frozenset({ModelLifecycleState.CANDIDATE}),
    ModelLifecycleState.CANDIDATE: frozenset(
        {ModelLifecycleState.VALIDATED, ModelLifecycleState.VALIDATION_FAILED}
    ),
    ModelLifecycleState.VALIDATION_FAILED: frozenset({ModelLifecycleState.ARCHIVED}),
    ModelLifecycleState.VALIDATED: frozenset(
        {ModelLifecycleState.STAGING, ModelLifecycleState.RETIRED}
    ),
    ModelLifecycleState.STAGING: frozenset(
        {
            ModelLifecycleState.CHALLENGER,
            ModelLifecycleState.VALIDATION_FAILED,
            ModelLifecycleState.RETIRED,
        }
    ),
    ModelLifecycleState.CHALLENGER: frozenset(
        {
            ModelLifecycleState.CHAMPION,
            ModelLifecycleState.DEGRADED,
            ModelLifecycleState.RETIRED,
        }
    ),
    ModelLifecycleState.CHAMPION: frozenset(
        {
            ModelLifecycleState.CHALLENGER,
            ModelLifecycleState.DEGRADED,
            ModelLifecycleState.ROLLED_BACK,
            ModelLifecycleState.RETIRED,
        }
    ),
    ModelLifecycleState.DEGRADED: frozenset(
        {
            ModelLifecycleState.CHALLENGER,
            ModelLifecycleState.ROLLED_BACK,
            ModelLifecycleState.RETIRED,
        }
    ),
    ModelLifecycleState.ROLLED_BACK: frozenset(
        {ModelLifecycleState.CHALLENGER, ModelLifecycleState.RETIRED, ModelLifecycleState.ARCHIVED}
    ),
    ModelLifecycleState.RETIRED: frozenset(
        {ModelLifecycleState.CHALLENGER, ModelLifecycleState.ARCHIVED}
    ),
    ModelLifecycleState.ARCHIVED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ModelDeploymentScope:
    """Unique serving scope for one target and learning task."""

    environment: str
    target_key: str
    task: LearningTask
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        environment = self.environment.strip().lower()
        target_key = self.target_key.strip().lower()
        if not _NAME.fullmatch(environment) or not target_key:
            raise DomainValidationError("Deployment scope requires a safe environment and target")
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "target_key", target_key)
        payload = f"{environment}|{target_key}|{self.task.value}".encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(payload).hexdigest())


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    transition_id: RegistryTransitionId
    model_version_id: ModelVersionId
    sequence: int
    previous_state: ModelLifecycleState | None
    next_state: ModelLifecycleState
    actor: str
    reason: str
    occurred_at: UtcInstant
    evidence_references: tuple[str, ...] = ()
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        actor = self.actor.strip()
        reason = self.reason.strip()
        evidence = tuple(item.strip() for item in self.evidence_references if item.strip())
        if self.sequence <= 0 or not actor or not reason:
            raise DomainValidationError("Lifecycle transition requires sequence, actor, and reason")
        if len(set(evidence)) != len(evidence):
            raise DomainValidationError("Lifecycle evidence references must be unique")
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "evidence_references", evidence)
        payload = {
            "id": str(self.transition_id),
            "model": str(self.model_version_id),
            "sequence": self.sequence,
            "previous": self.previous_state.value if self.previous_state else None,
            "next": self.next_state.value,
            "actor": actor,
            "reason": reason,
            "occurred_at": self.occurred_at.isoformat(),
            "evidence": evidence,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())


@dataclass(frozen=True, slots=True)
class RegisteredModelVersion:
    """Immutable current view of a registered model version."""

    model_version_id: ModelVersionId
    training_run_id: ExperimentRunId
    scope: ModelDeploymentScope
    artifact: ModelArtifact
    model_card: ModelCard
    state: ModelLifecycleState
    revision: int
    registered_at: UtcInstant
    updated_at: UtcInstant
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.revision <= 0 or self.updated_at < self.registered_at:
            raise DomainValidationError("Registered model revision and timestamps are invalid")
        if self.artifact.model_version_id != self.model_version_id:
            raise DomainValidationError("Registered artifact belongs to another model version")
        if self.model_card.model_version_id != self.model_version_id:
            raise DomainValidationError("Registered model card belongs to another model version")
        if self.artifact.signature.target_key != self.scope.target_key:
            raise DomainValidationError("Model target differs from deployment scope")
        if self.artifact.signature.task is not self.scope.task:
            raise DomainValidationError("Model task differs from deployment scope")
        self.artifact.verify()
        payload = {
            "model": str(self.model_version_id),
            "run": str(self.training_run_id),
            "scope": self.scope.fingerprint,
            "artifact": self.artifact.payload_sha256,
            "card": self.model_card.training_dataset_fingerprint,
            "state": self.state.value,
            "revision": self.revision,
            "registered_at": self.registered_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    def transition(
        self,
        next_state: ModelLifecycleState,
        *,
        actor: str,
        reason: str,
        occurred_at: UtcInstant,
        evidence_references: tuple[str, ...] = (),
    ) -> tuple[RegisteredModelVersion, LifecycleTransition]:
        if next_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ModelRegistryError(
                f"Illegal model transition: {self.state.value} -> {next_state.value}"
            )
        if occurred_at < self.updated_at:
            raise ModelRegistryError("Lifecycle transition cannot move backward in time")
        updated = replace(
            self,
            state=next_state,
            revision=self.revision + 1,
            updated_at=occurred_at,
        )
        transition = LifecycleTransition(
            transition_id=RegistryTransitionId.new(),
            model_version_id=self.model_version_id,
            sequence=updated.revision,
            previous_state=self.state,
            next_state=next_state,
            actor=actor,
            reason=reason,
            occurred_at=occurred_at,
            evidence_references=evidence_references,
        )
        return updated, transition


@dataclass(frozen=True, slots=True)
class ModelApproval:
    actor: str
    role: ApprovalRole
    decision: ApprovalDecision
    decided_at: UtcInstant
    comment: str

    def __post_init__(self) -> None:
        actor = self.actor.strip()
        comment = self.comment.strip()
        if not actor or not comment:
            raise DomainValidationError("Model approval requires actor and comment")
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "comment", comment)


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool
    evidence_reference: str
    detail: str

    def __post_init__(self) -> None:
        name = self.name.strip().lower()
        evidence = self.evidence_reference.strip()
        detail = self.detail.strip()
        if not _NAME.fullmatch(name) or not evidence or not detail:
            raise DomainValidationError("Promotion gate requires name, evidence, and detail")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "evidence_reference", evidence)
        object.__setattr__(self, "detail", detail)


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    gates: tuple[GateResult, ...]
    approvals: tuple[ModelApproval, ...]
    collected_at: UtcInstant
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        gate_names = tuple(item.name for item in self.gates)
        approval_keys = tuple((item.actor, item.role) for item in self.approvals)
        if not self.gates or len(set(gate_names)) != len(gate_names):
            raise DomainValidationError("Promotion evidence requires unique gates")
        if len(set(approval_keys)) != len(approval_keys):
            raise DomainValidationError("Promotion approvals must be unique by actor and role")
        payload = {
            "gates": [
                (item.name, item.passed, item.evidence_reference, item.detail)
                for item in self.gates
            ],
            "approvals": [
                (
                    item.actor,
                    item.role.value,
                    item.decision.value,
                    item.decided_at.isoformat(),
                    item.comment,
                )
                for item in self.approvals
            ],
            "collected_at": self.collected_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    accepted: bool
    reasons: tuple[str, ...]
    evidence_fingerprint: str
    evaluated_at: UtcInstant

    def __post_init__(self) -> None:
        if self.accepted and self.reasons:
            raise DomainValidationError(
                "Accepted promotion decisions cannot have rejection reasons"
            )
        if not self.accepted and not self.reasons:
            raise DomainValidationError("Rejected promotion decisions require reasons")


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    required_gate_names: tuple[str, ...]
    required_approval_roles: tuple[ApprovalRole, ...]

    def __post_init__(self) -> None:
        names = tuple(item.strip().lower() for item in self.required_gate_names)
        if not names or len(set(names)) != len(names):
            raise DomainValidationError("Promotion policy requires unique gates")
        if not self.required_approval_roles or len(
            set(self.required_approval_roles)
        ) != len(self.required_approval_roles):
            raise DomainValidationError(
                "Promotion approval roles must be unique and non-empty"
            )
        object.__setattr__(self, "required_gate_names", names)

    def evaluate(
        self, evidence: PromotionEvidence, evaluated_at: UtcInstant
    ) -> PromotionDecision:
        gates = {item.name: item for item in evidence.gates}
        reasons: list[str] = []
        for name in self.required_gate_names:
            gate = gates.get(name)
            if gate is None:
                reasons.append(f"required gate is missing: {name}")
            elif not gate.passed:
                reasons.append(f"required gate failed: {name}")
        approved_roles = {
            item.role
            for item in evidence.approvals
            if item.decision is ApprovalDecision.APPROVED
        }
        rejected_roles = {
            item.role
            for item in evidence.approvals
            if item.decision is ApprovalDecision.REJECTED
        }
        for role in self.required_approval_roles:
            if role in rejected_roles:
                reasons.append(f"approval was rejected: {role.value}")
            elif role not in approved_roles:
                reasons.append(f"required approval is missing: {role.value}")
        return PromotionDecision(
            accepted=not reasons,
            reasons=tuple(reasons),
            evidence_fingerprint=evidence.fingerprint,
            evaluated_at=evaluated_at,
        )


@dataclass(frozen=True, slots=True)
class AliasBinding:
    scope: ModelDeploymentScope
    alias: RegistryAlias
    model_version_id: ModelVersionId | None
    bound_at: UtcInstant


@dataclass(frozen=True, slots=True)
class ModelDeployment:
    deployment_id: ModelDeploymentId
    scope: ModelDeploymentScope
    model_version_id: ModelVersionId
    mode: DeploymentMode
    status: DeploymentStatus
    deployed_at: UtcInstant
    ended_at: UtcInstant | None
    previous_model_version_id: ModelVersionId | None
    reason: str

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            raise DomainValidationError("Model deployment requires a reason")
        if self.status is DeploymentStatus.ACTIVE and self.ended_at is not None:
            raise DomainValidationError("Active deployments cannot have an end time")
        if self.status is not DeploymentStatus.ACTIVE and self.ended_at is None:
            raise DomainValidationError("Ended deployments require an end time")
        if self.ended_at is not None and self.ended_at < self.deployed_at:
            raise DomainValidationError("Deployment end cannot precede deployment")
        object.__setattr__(self, "reason", reason)

    def end(
        self, status: DeploymentStatus, ended_at: UtcInstant, reason: str
    ) -> ModelDeployment:
        if self.status is not DeploymentStatus.ACTIVE:
            raise ModelRegistryError("Only active deployments can be ended")
        if status is DeploymentStatus.ACTIVE:
            raise ModelRegistryError("Ended deployment status cannot remain active")
        return replace(self, status=status, ended_at=ended_at, reason=reason.strip())


@dataclass(frozen=True, slots=True)
class RegistryMutation:
    record: RegisteredModelVersion
    transition: LifecycleTransition
    expected_revision: int

    def __post_init__(self) -> None:
        if self.expected_revision <= 0:
            raise DomainValidationError("Registry mutation requires a positive expected revision")
        if self.record.revision != self.expected_revision + 1:
            raise DomainValidationError("Registry mutation revision must advance exactly once")
        if self.transition.sequence != self.record.revision:
            raise DomainValidationError("Transition sequence must match record revision")


@dataclass(frozen=True, slots=True)
class AliasMutation:
    binding: AliasBinding
    expected_model_version_id: ModelVersionId | None


@dataclass(frozen=True, slots=True)
class RegistryRelease:
    mutations: tuple[RegistryMutation, ...]
    alias_mutations: tuple[AliasMutation, ...] = ()
    deployments: tuple[ModelDeployment, ...] = ()

    def __post_init__(self) -> None:
        model_ids = tuple(item.record.model_version_id for item in self.mutations)
        alias_keys = tuple(
            (item.binding.scope.fingerprint, item.binding.alias)
            for item in self.alias_mutations
        )
        deployment_ids = tuple(item.deployment_id for item in self.deployments)
        if not self.mutations:
            raise DomainValidationError("Registry release requires at least one model mutation")
        if len(set(model_ids)) != len(model_ids):
            raise DomainValidationError("Registry release cannot mutate a model twice")
        if len(set(alias_keys)) != len(alias_keys):
            raise DomainValidationError("Registry release aliases must be unique")
        if len(set(deployment_ids)) != len(deployment_ids):
            raise DomainValidationError("Registry deployment mutations must be unique")
