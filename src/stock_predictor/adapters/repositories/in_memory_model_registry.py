"""Thread-safe in-memory reference adapter for the governed model registry."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    ImmutableObjectConflictError,
)
from stock_predictor.domain.common.identifiers import ModelDeploymentId, ModelVersionId
from stock_predictor.domain.mlops.registry import (
    DeploymentMode,
    DeploymentStatus,
    LifecycleTransition,
    ModelDeployment,
    ModelDeploymentScope,
    ModelLifecycleState,
    RegisteredModelVersion,
    RegistryAlias,
    RegistryRelease,
)


class InMemoryModelRegistryRepository:
    __slots__ = ("_aliases", "_deployments", "_history", "_lock", "_records")

    def __init__(self) -> None:
        self._records: dict[ModelVersionId, RegisteredModelVersion] = {}
        self._history: dict[ModelVersionId, list[LifecycleTransition]] = {}
        self._aliases: dict[tuple[str, RegistryAlias], ModelVersionId] = {}
        self._deployments: dict[ModelDeploymentId, ModelDeployment] = {}
        self._lock = RLock()

    def register(
        self,
        record: RegisteredModelVersion,
        transition: LifecycleTransition,
    ) -> None:
        with self._lock:
            existing = self._records.get(record.model_version_id)
            if existing is not None:
                if existing.fingerprint == record.fingerprint:
                    return
                raise ImmutableObjectConflictError("Model version is already registered")
            if record.revision != 1 or transition.sequence != 1:
                raise DomainConflictError("Initial registry revision and transition must be one")
            if transition.previous_state is not None or transition.next_state is not record.state:
                raise DomainConflictError("Initial transition does not match registered state")
            self._records[record.model_version_id] = record
            self._history[record.model_version_id] = [transition]

    def get(self, model_version_id: ModelVersionId) -> RegisteredModelVersion:
        with self._lock:
            try:
                return self._records[model_version_id]
            except KeyError as exc:
                raise DomainNotFoundError(
                    f"Model version is not registered: {model_version_id}"
                ) from exc

    def list(
        self,
        *,
        scope: ModelDeploymentScope | None = None,
        state: ModelLifecycleState | None = None,
    ) -> tuple[RegisteredModelVersion, ...]:
        with self._lock:
            values = tuple(self._records.values())
        filtered = tuple(
            item
            for item in values
            if (scope is None or item.scope == scope)
            and (state is None or item.state is state)
        )
        return tuple(
            sorted(
                filtered,
                key=lambda item: (item.registered_at, str(item.model_version_id)),
            )
        )

    def history(self, model_version_id: ModelVersionId) -> tuple[LifecycleTransition, ...]:
        with self._lock:
            try:
                return tuple(self._history[model_version_id])
            except KeyError as exc:
                raise DomainNotFoundError(
                    f"Model version is not registered: {model_version_id}"
                ) from exc

    def resolve_alias(
        self,
        scope: ModelDeploymentScope,
        alias: RegistryAlias,
    ) -> RegisteredModelVersion | None:
        with self._lock:
            model_id = self._aliases.get((scope.fingerprint, alias))
            return self._records.get(model_id) if model_id is not None else None

    def deployment_history(
        self, scope: ModelDeploymentScope
    ) -> tuple[ModelDeployment, ...]:
        with self._lock:
            result = tuple(
                item for item in self._deployments.values() if item.scope == scope
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (item.deployed_at, str(item.deployment_id)),
            )
        )

    def commit_release(self, release: RegistryRelease) -> None:
        with self._lock:
            self._validate_mutations(release)
            self._validate_aliases(release)
            proposed_deployments = dict(self._deployments)
            self._validate_and_stage_deployments(release, proposed_deployments)
            for mutation in release.mutations:
                model_id = mutation.record.model_version_id
                self._records[model_id] = mutation.record
                self._history[model_id].append(mutation.transition)
            for mutation in release.alias_mutations:
                key = (mutation.binding.scope.fingerprint, mutation.binding.alias)
                if mutation.binding.model_version_id is None:
                    self._aliases.pop(key, None)
                else:
                    self._aliases[key] = mutation.binding.model_version_id
            self._deployments = proposed_deployments

    def _validate_mutations(self, release: RegistryRelease) -> None:
        for mutation in release.mutations:
            model_id = mutation.record.model_version_id
            current = self._records.get(model_id)
            if current is None:
                raise DomainNotFoundError(f"Model version is not registered: {model_id}")
            if current.revision != mutation.expected_revision:
                raise DomainConflictError(
                    f"Model registry revision conflict for {model_id}: "
                    f"expected {mutation.expected_revision}, found {current.revision}"
                )
            if mutation.transition.previous_state is not current.state:
                raise DomainConflictError("Registry transition previous state is stale")
            if mutation.transition.model_version_id != model_id:
                raise DomainConflictError("Registry transition belongs to another model")

    def _validate_aliases(self, release: RegistryRelease) -> None:
        records_after = {
            **self._records,
            **{item.record.model_version_id: item.record for item in release.mutations},
        }
        for mutation in release.alias_mutations:
            key = (mutation.binding.scope.fingerprint, mutation.binding.alias)
            current = self._aliases.get(key)
            if current != mutation.expected_model_version_id:
                raise DomainConflictError("Model alias changed concurrently")
            model_id = mutation.binding.model_version_id
            if model_id is None:
                continue
            record = records_after.get(model_id)
            if record is None or record.scope != mutation.binding.scope:
                raise DomainConflictError("Alias target is absent or belongs to another scope")
            expected_state = (
                ModelLifecycleState.CHAMPION
                if mutation.binding.alias is RegistryAlias.CHAMPION
                else ModelLifecycleState.CHALLENGER
            )
            if record.state is not expected_state:
                raise DomainConflictError(
                    f"Alias {mutation.binding.alias.value} requires {expected_state.value} state"
                )

    def _validate_and_stage_deployments(
        self,
        release: RegistryRelease,
        proposed: dict[ModelDeploymentId, ModelDeployment],
    ) -> None:
        records_after = {
            **self._records,
            **{item.record.model_version_id: item.record for item in release.mutations},
        }
        for deployment in release.deployments:
            existing = proposed.get(deployment.deployment_id)
            if existing is None:
                if deployment.status is not DeploymentStatus.ACTIVE:
                    raise DomainConflictError("New deployment records must start active")
                record = records_after.get(deployment.model_version_id)
                if record is None or record.scope != deployment.scope:
                    raise DomainConflictError("Deployment model is absent or in another scope")
            else:
                if existing.status is not DeploymentStatus.ACTIVE:
                    raise DomainConflictError("Only active deployment records can be updated")
                immutable = (
                    existing.scope,
                    existing.model_version_id,
                    existing.mode,
                    existing.deployed_at,
                    existing.previous_model_version_id,
                )
                updated_immutable = (
                    deployment.scope,
                    deployment.model_version_id,
                    deployment.mode,
                    deployment.deployed_at,
                    deployment.previous_model_version_id,
                )
                if immutable != updated_immutable:
                    raise ImmutableObjectConflictError(
                        "Deployment update changed immutable identity fields"
                    )
            proposed[deployment.deployment_id] = deployment
        active_keys: set[tuple[str, DeploymentMode]] = set()
        for deployment in proposed.values():
            if deployment.status is not DeploymentStatus.ACTIVE:
                continue
            key = (deployment.scope.fingerprint, deployment.mode)
            if key in active_keys:
                raise DomainConflictError(
                    "Only one active deployment per scope and mode is allowed"
                )
            active_keys.add(key)
