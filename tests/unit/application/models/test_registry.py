from typing import cast

import pytest

from stock_predictor.adapters.models.baselines import (
    HistoricalMeanRegressorPlugin,
    MajorityClassifierPlugin,
)
from stock_predictor.application.models.registry import ModelPluginRegistry
from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
)
from stock_predictor.domain.modeling.models import LearningTask
from stock_predictor.ports.model_plugin import ModelPlugin


def test_model_plugin_registry_enforces_unique_task_aware_lookup() -> None:
    mean = HistoricalMeanRegressorPlugin()
    majority = MajorityClassifierPlugin()
    registry = ModelPluginRegistry((mean, majority))

    assert registry.get(mean.key, LearningTask.REGRESSION) is mean
    assert registry.all() == (mean, majority)

    with pytest.raises(DomainConflictError, match="already registered"):
        registry.register(mean)
    with pytest.raises(DomainNotFoundError, match="not registered"):
        registry.get("missing")
    with pytest.raises(DomainNotFoundError, match="does not support"):
        registry.get(mean.key, LearningTask.BINARY_CLASSIFICATION)


def test_model_plugin_registry_rejects_invalid_plugin_metadata() -> None:
    class BlankPlugin:
        key = " "
        supported_tasks = (LearningTask.REGRESSION,)

    class NoTasksPlugin:
        key = "invalid.no_tasks"
        supported_tasks = ()

    class DuplicateTasksPlugin:
        key = "invalid.duplicate_tasks"
        supported_tasks = (LearningTask.REGRESSION, LearningTask.REGRESSION)

    registry = ModelPluginRegistry()
    with pytest.raises(DomainValidationError, match="key is required"):
        registry.register(cast(ModelPlugin, BlankPlugin()))
    with pytest.raises(DomainValidationError, match="unique supported"):
        registry.register(cast(ModelPlugin, NoTasksPlugin()))
    with pytest.raises(DomainValidationError, match="unique supported"):
        registry.register(cast(ModelPlugin, DuplicateTasksPlugin()))
