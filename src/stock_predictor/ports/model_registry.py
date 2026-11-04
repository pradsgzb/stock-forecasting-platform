"""Port for a governed, append-only model registry."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import ModelVersionId
from stock_predictor.domain.mlops.registry import (
    LifecycleTransition,
    ModelDeployment,
    ModelDeploymentScope,
    ModelLifecycleState,
    RegisteredModelVersion,
    RegistryAlias,
    RegistryRelease,
)


@runtime_checkable
class ModelRegistryRepository(Protocol):
    def register(
        self,
        record: RegisteredModelVersion,
        transition: LifecycleTransition,
    ) -> None:
        ...

    def get(self, model_version_id: ModelVersionId) -> RegisteredModelVersion:
        ...

    def list(
        self,
        *,
        scope: ModelDeploymentScope | None = None,
        state: ModelLifecycleState | None = None,
    ) -> tuple[RegisteredModelVersion, ...]:
        ...

    def history(self, model_version_id: ModelVersionId) -> tuple[LifecycleTransition, ...]:
        ...

    def resolve_alias(
        self,
        scope: ModelDeploymentScope,
        alias: RegistryAlias,
    ) -> RegisteredModelVersion | None:
        ...

    def deployment_history(
        self, scope: ModelDeploymentScope
    ) -> tuple[ModelDeployment, ...]:
        ...

    def commit_release(self, release: RegistryRelease) -> None:
        ...
