"""Deterministic grid and bounded random hyperparameter search strategies."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Mapping

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.modeling.models import (
    HyperParameterValue,
    LearningTask,
    ModelFamily,
    ModelSpec,
    normalize_hyperparameter,
)


@dataclass(frozen=True, slots=True)
class ModelSearchDefinition:
    name: str
    version: str
    family: ModelFamily
    task: LearningTask
    plugin_key: str
    parameter_grid: tuple[tuple[str, tuple[HyperParameterValue, ...]], ...] = ()

    @classmethod
    def create(
        cls,
        *,
        name: str,
        version: str,
        family: ModelFamily,
        task: LearningTask,
        plugin_key: str,
        parameter_grid: Mapping[str, tuple[object, ...]] | None = None,
    ) -> ModelSearchDefinition:
        normalized: list[tuple[str, tuple[HyperParameterValue, ...]]] = []
        for key, values in sorted((parameter_grid or {}).items()):
            if not values:
                raise DomainValidationError(
                    f"Hyperparameter search values cannot be empty: {key}"
                )
            normalized.append(
                (
                    key.strip(),
                    tuple(
                        normalize_hyperparameter(item, name=key)
                        for item in values
                    ),
                )
            )
        return cls(
            name=name,
            version=version,
            family=family,
            task=task,
            plugin_key=plugin_key,
            parameter_grid=tuple(normalized),
        )

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip() or not self.plugin_key.strip():
            raise DomainValidationError("Model search identity fields are required")
        keys = tuple(item[0] for item in self.parameter_grid)
        if len(set(keys)) != len(keys) or any(not key for key in keys):
            raise DomainValidationError("Search hyperparameter names must be unique")

    def all_combinations(self) -> tuple[tuple[tuple[str, HyperParameterValue], ...], ...]:
        if not self.parameter_grid:
            return ((),)
        names = tuple(item[0] for item in self.parameter_grid)
        products = itertools.product(*(item[1] for item in self.parameter_grid))
        return tuple(
            tuple(zip(names, values, strict=True))
            for values in products
        )


class GridSearchStrategy:
    def candidates(
        self,
        definitions: tuple[ModelSearchDefinition, ...],
        *,
        random_seed: int,
        maximum_trials: int,
    ) -> tuple[ModelSpec, ...]:
        if maximum_trials <= 0 or random_seed < 0:
            raise DomainValidationError("Search limits and seed are invalid")
        result: list[ModelSpec] = []
        for definition in definitions:
            for parameters in definition.all_combinations():
                result.append(
                    ModelSpec(
                        name=definition.name,
                        version=definition.version,
                        family=definition.family,
                        task=definition.task,
                        plugin_key=definition.plugin_key,
                        random_seed=random_seed + len(result),
                        hyperparameters=parameters,
                    )
                )
                if len(result) >= maximum_trials:
                    return tuple(result)
        return tuple(result)


class RandomSearchStrategy:
    """Deterministically samples without replacement from finite declared grids."""

    def candidates(
        self,
        definitions: tuple[ModelSearchDefinition, ...],
        *,
        random_seed: int,
        maximum_trials: int,
    ) -> tuple[ModelSpec, ...]:
        all_candidates = GridSearchStrategy().candidates(
            definitions,
            random_seed=random_seed,
            maximum_trials=sum(
                len(item.all_combinations()) for item in definitions
            ),
        )
        if maximum_trials <= 0:
            raise DomainValidationError("Maximum trials must be positive")
        if maximum_trials >= len(all_candidates):
            return all_candidates
        generator = random.Random(random_seed)
        selected = sorted(generator.sample(range(len(all_candidates)), maximum_trials))
        return tuple(all_candidates[index] for index in selected)
