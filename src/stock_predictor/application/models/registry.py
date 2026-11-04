"""Registry for replaceable model-training plugins."""

from __future__ import annotations

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
)
from stock_predictor.domain.modeling.models import LearningTask
from stock_predictor.ports.model_plugin import ModelPlugin


class ModelPluginRegistry:
    __slots__ = ("_plugins",)

    def __init__(self, plugins: tuple[ModelPlugin, ...] = ()) -> None:
        self._plugins: dict[str, ModelPlugin] = {}
        for plugin in plugins:
            self.register(plugin)

    def register(self, plugin: ModelPlugin) -> None:
        key = plugin.key.strip().lower()
        if not key:
            raise DomainValidationError("Model plugin key is required")
        if not plugin.supported_tasks or len(set(plugin.supported_tasks)) != len(
            plugin.supported_tasks
        ):
            raise DomainValidationError(
                "Model plugin must declare unique supported learning tasks"
            )
        if key in self._plugins:
            raise DomainConflictError(f"Model plugin is already registered: {key}")
        self._plugins[key] = plugin

    def get(self, key: str, task: LearningTask | None = None) -> ModelPlugin:
        normalized = key.strip().lower()
        try:
            plugin = self._plugins[normalized]
        except KeyError as exc:
            raise DomainNotFoundError(f"Model plugin is not registered: {normalized}") from exc
        if task is not None and task not in plugin.supported_tasks:
            raise DomainNotFoundError(
                f"Model plugin {normalized} does not support task {task.value}"
            )
        return plugin

    def all(self) -> tuple[ModelPlugin, ...]:
        return tuple(self._plugins[key] for key in sorted(self._plugins))
