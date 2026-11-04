"""Application service for governed model registration, promotion, and rollback."""

from __future__ import annotations

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import ModelRegistryError
from stock_predictor.domain.common.identifiers import (
    ModelDeploymentId,
    ModelVersionId,
    RegistryTransitionId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.mlops.registry import (
    AliasBinding,
    AliasMutation,
    DeploymentMode,
    DeploymentStatus,
    LifecycleTransition,
    ModelDeployment,
    ModelDeploymentScope,
    ModelLifecycleState,
    PromotionDecision,
    PromotionEvidence,
    PromotionPolicy,
    RegisteredModelVersion,
    RegistryAlias,
    RegistryMutation,
    RegistryRelease,
)
from stock_predictor.domain.modeling.training import TrainingResult
from stock_predictor.ports.model_registry import ModelRegistryRepository


class ModelRegistryService:
    __slots__ = ("_clock", "_policy", "_repository")

    def __init__(
        self,
        repository: ModelRegistryRepository,
        clock: Clock,
        promotion_policy: PromotionPolicy,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._policy = promotion_policy

    def register_candidate(
        self,
        training_result: TrainingResult,
        scope: ModelDeploymentScope,
        *,
        actor: str,
    ) -> RegisteredModelVersion:
        now = self._clock.now()
        record = RegisteredModelVersion(
            model_version_id=training_result.model_version_id,
            training_run_id=training_result.run_id,
            scope=scope,
            artifact=training_result.artifact,
            model_card=training_result.model_card,
            state=ModelLifecycleState.CANDIDATE,
            revision=1,
            registered_at=now,
            updated_at=now,
        )
        transition = LifecycleTransition(
            transition_id=RegistryTransitionId.new(),
            model_version_id=record.model_version_id,
            sequence=1,
            previous_state=None,
            next_state=ModelLifecycleState.CANDIDATE,
            actor=actor,
            reason="training pipeline registered a candidate",
            occurred_at=now,
            evidence_references=(
                training_result.artifact.payload_sha256,
                training_result.holdout_report.fingerprint,
            ),
        )
        self._repository.register(record, transition)
        return record

    def validate_candidate(
        self,
        model_version_id: ModelVersionId,
        evidence: PromotionEvidence,
        *,
        actor: str,
    ) -> tuple[RegisteredModelVersion, PromotionDecision]:
        now = self._clock.now()
        decision = self._policy.evaluate(evidence, now)
        state = (
            ModelLifecycleState.VALIDATED
            if decision.accepted
            else ModelLifecycleState.VALIDATION_FAILED
        )
        reason = (
            "candidate passed governed validation gates"
            if decision.accepted
            else "; ".join(decision.reasons)
        )
        record = self._transition(
            model_version_id,
            state,
            actor=actor,
            reason=reason,
            evidence_references=(evidence.fingerprint,),
        )
        return record, decision

    def stage(
        self,
        model_version_id: ModelVersionId,
        *,
        actor: str,
        reason: str = "validated model prepared for controlled deployment",
    ) -> RegisteredModelVersion:
        return self._transition(
            model_version_id,
            ModelLifecycleState.STAGING,
            actor=actor,
            reason=reason,
        )

    def deploy_challenger(
        self,
        model_version_id: ModelVersionId,
        *,
        actor: str,
        reason: str,
        mode: DeploymentMode = DeploymentMode.SHADOW,
    ) -> ModelDeployment:
        if mode is DeploymentMode.ACTIVE:
            raise ModelRegistryError("Challenger deployment must use shadow or canary mode")
        now = self._clock.now()
        target = self._repository.get(model_version_id)
        updated, transition = target.transition(
            ModelLifecycleState.CHALLENGER,
            actor=actor,
            reason=reason,
            occurred_at=now,
        )
        mutations = [RegistryMutation(updated, transition, target.revision)]
        deployments: list[ModelDeployment] = []
        current_challenger = self._repository.resolve_alias(
            target.scope, RegistryAlias.CHALLENGER
        )
        expected_challenger = (
            current_challenger.model_version_id if current_challenger is not None else None
        )
        if current_challenger is not None and current_challenger != target:
            retired, retired_transition = current_challenger.transition(
                ModelLifecycleState.RETIRED,
                actor=actor,
                reason="superseded by a new challenger",
                occurred_at=now,
            )
            mutations.append(
                RegistryMutation(
                    retired,
                    retired_transition,
                    current_challenger.revision,
                )
            )
            deployments.extend(
                self._end_active_deployments(
                    target.scope,
                    current_challenger.model_version_id,
                    now,
                    DeploymentStatus.SUPERSEDED,
                    "superseded by a new challenger",
                    modes=(DeploymentMode.SHADOW, DeploymentMode.CANARY),
                )
            )
        deployment = ModelDeployment(
            deployment_id=ModelDeploymentId.new(),
            scope=target.scope,
            model_version_id=target.model_version_id,
            mode=mode,
            status=DeploymentStatus.ACTIVE,
            deployed_at=now,
            ended_at=None,
            previous_model_version_id=expected_challenger,
            reason=reason,
        )
        deployments.append(deployment)
        release = RegistryRelease(
            mutations=tuple(mutations),
            alias_mutations=(
                AliasMutation(
                    AliasBinding(
                        target.scope,
                        RegistryAlias.CHALLENGER,
                        target.model_version_id,
                        now,
                    ),
                    expected_challenger,
                ),
            ),
            deployments=tuple(deployments),
        )
        self._repository.commit_release(release)
        return deployment

    def promote_challenger(
        self,
        model_version_id: ModelVersionId,
        evidence: PromotionEvidence,
        *,
        actor: str,
        reason: str,
    ) -> tuple[ModelDeployment, PromotionDecision]:
        now = self._clock.now()
        decision = self._policy.evaluate(evidence, now)
        if not decision.accepted:
            raise ModelRegistryError(
                "Champion promotion was rejected: " + "; ".join(decision.reasons)
            )
        target = self._repository.get(model_version_id)
        challenger_alias = self._repository.resolve_alias(
            target.scope, RegistryAlias.CHALLENGER
        )
        if challenger_alias is None or challenger_alias.model_version_id != model_version_id:
            raise ModelRegistryError("Only the assigned challenger can be promoted")
        promoted, promoted_transition = target.transition(
            ModelLifecycleState.CHAMPION,
            actor=actor,
            reason=reason,
            occurred_at=now,
            evidence_references=(evidence.fingerprint,),
        )
        mutations = [RegistryMutation(promoted, promoted_transition, target.revision)]
        current_champion = self._repository.resolve_alias(
            target.scope, RegistryAlias.CHAMPION
        )
        expected_champion = (
            current_champion.model_version_id if current_champion is not None else None
        )
        if current_champion is not None:
            demoted, demoted_transition = current_champion.transition(
                ModelLifecycleState.CHALLENGER,
                actor=actor,
                reason="superseded by promoted challenger",
                occurred_at=now,
                evidence_references=(evidence.fingerprint,),
            )
            mutations.append(
                RegistryMutation(
                    demoted,
                    demoted_transition,
                    current_champion.revision,
                )
            )
        deployments = list(
            self._end_active_deployments(
                target.scope,
                target.model_version_id,
                now,
                DeploymentStatus.SUPERSEDED,
                "challenger deployment replaced by active deployment",
                modes=(DeploymentMode.SHADOW, DeploymentMode.CANARY),
            )
        )
        if current_champion is not None:
            deployments.extend(
                self._end_active_deployments(
                    target.scope,
                    current_champion.model_version_id,
                    now,
                    DeploymentStatus.SUPERSEDED,
                    "champion superseded by approved challenger",
                    modes=(DeploymentMode.ACTIVE,),
                )
            )
        deployment = ModelDeployment(
            deployment_id=ModelDeploymentId.new(),
            scope=target.scope,
            model_version_id=target.model_version_id,
            mode=DeploymentMode.ACTIVE,
            status=DeploymentStatus.ACTIVE,
            deployed_at=now,
            ended_at=None,
            previous_model_version_id=expected_champion,
            reason=reason,
        )
        deployments.append(deployment)
        release = RegistryRelease(
            mutations=tuple(mutations),
            alias_mutations=(
                AliasMutation(
                    AliasBinding(
                        target.scope,
                        RegistryAlias.CHAMPION,
                        target.model_version_id,
                        now,
                    ),
                    expected_champion,
                ),
                AliasMutation(
                    AliasBinding(
                        target.scope,
                        RegistryAlias.CHALLENGER,
                        expected_champion,
                        now,
                    ),
                    target.model_version_id,
                ),
            ),
            deployments=tuple(deployments),
        )
        self._repository.commit_release(release)
        return deployment, decision

    def mark_degraded(
        self,
        model_version_id: ModelVersionId,
        *,
        actor: str,
        reason: str,
        evidence_references: tuple[str, ...],
    ) -> RegisteredModelVersion:
        return self._transition(
            model_version_id,
            ModelLifecycleState.DEGRADED,
            actor=actor,
            reason=reason,
            evidence_references=evidence_references,
        )

    def rollback(
        self,
        scope: ModelDeploymentScope,
        *,
        actor: str,
        reason: str,
        evidence_references: tuple[str, ...] = (),
    ) -> ModelDeployment:
        now = self._clock.now()
        current = self._repository.resolve_alias(scope, RegistryAlias.CHAMPION)
        if current is None:
            raise ModelRegistryError("No champion is assigned for rollback")
        active = self._active_deployment(scope, DeploymentMode.ACTIVE)
        if active is None or active.model_version_id != current.model_version_id:
            raise ModelRegistryError("Champion has no active deployment to roll back")
        previous_id = active.previous_model_version_id
        if previous_id is None:
            raise ModelRegistryError("Champion deployment has no rollback predecessor")
        previous = self._repository.get(previous_id)
        rolled_back, current_transition = current.transition(
            ModelLifecycleState.ROLLED_BACK,
            actor=actor,
            reason=reason,
            occurred_at=now,
            evidence_references=evidence_references,
        )
        restored, previous_transition = previous.transition(
            ModelLifecycleState.CHAMPION,
            actor=actor,
            reason="restored as the last known champion",
            occurred_at=now,
            evidence_references=evidence_references,
        )
        ended = active.end(DeploymentStatus.ROLLED_BACK, now, reason)
        deployment = ModelDeployment(
            deployment_id=ModelDeploymentId.new(),
            scope=scope,
            model_version_id=previous_id,
            mode=DeploymentMode.ACTIVE,
            status=DeploymentStatus.ACTIVE,
            deployed_at=now,
            ended_at=None,
            previous_model_version_id=current.model_version_id,
            reason="rollback restored previous champion",
        )
        release = RegistryRelease(
            mutations=(
                RegistryMutation(rolled_back, current_transition, current.revision),
                RegistryMutation(restored, previous_transition, previous.revision),
            ),
            alias_mutations=(
                AliasMutation(
                    AliasBinding(scope, RegistryAlias.CHAMPION, previous_id, now),
                    current.model_version_id,
                ),
                AliasMutation(
                    AliasBinding(
                        scope,
                        RegistryAlias.CHALLENGER,
                        None,
                        now,
                    ),
                    previous_id,
                ),
            ),
            deployments=(ended, deployment),
        )
        self._repository.commit_release(release)
        return deployment

    def _transition(
        self,
        model_version_id: ModelVersionId,
        state: ModelLifecycleState,
        *,
        actor: str,
        reason: str,
        evidence_references: tuple[str, ...] = (),
    ) -> RegisteredModelVersion:
        current = self._repository.get(model_version_id)
        updated, transition = current.transition(
            state,
            actor=actor,
            reason=reason,
            occurred_at=self._clock.now(),
            evidence_references=evidence_references,
        )
        self._repository.commit_release(
            RegistryRelease(
                mutations=(RegistryMutation(updated, transition, current.revision),)
            )
        )
        return updated

    def _active_deployment(
        self,
        scope: ModelDeploymentScope,
        mode: DeploymentMode,
    ) -> ModelDeployment | None:
        active = tuple(
            item
            for item in self._repository.deployment_history(scope)
            if item.mode is mode and item.status is DeploymentStatus.ACTIVE
        )
        if len(active) > 1:
            raise ModelRegistryError("Registry contains multiple active deployments")
        return active[0] if active else None

    def _end_active_deployments(
        self,
        scope: ModelDeploymentScope,
        model_version_id: ModelVersionId,
        ended_at: UtcInstant,
        status: DeploymentStatus,
        reason: str,
        *,
        modes: tuple[DeploymentMode, ...],
    ) -> tuple[ModelDeployment, ...]:
        return tuple(
            item.end(status, ended_at, reason)
            for item in self._repository.deployment_history(scope)
            if item.model_version_id == model_version_id
            and item.mode in modes
            and item.status is DeploymentStatus.ACTIVE
        )
