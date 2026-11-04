from decimal import Decimal

import pytest

from stock_predictor.application.training.search import (
    GridSearchStrategy,
    ModelSearchDefinition,
    RandomSearchStrategy,
)
from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.modeling.models import LearningTask, ModelFamily


def definitions():
    return (
        ModelSearchDefinition.create(
            name="ridge",
            version="1",
            family=ModelFamily.LINEAR,
            task=LearningTask.REGRESSION,
            plugin_key="linear.ridge",
            parameter_grid={"alpha": (Decimal("0.1"), Decimal("1"), Decimal("10"))},
        ),
    )


def test_grid_and_random_search_are_bounded_and_reproducible() -> None:
    grid = GridSearchStrategy().candidates(
        definitions(),
        random_seed=10,
        maximum_trials=2,
    )
    assert len(grid) == 2
    assert grid[0].random_seed == 10
    assert grid[1].parameter("alpha") == Decimal("1")

    first = RandomSearchStrategy().candidates(
        definitions(),
        random_seed=4,
        maximum_trials=2,
    )
    second = RandomSearchStrategy().candidates(
        definitions(),
        random_seed=4,
        maximum_trials=2,
    )
    assert first == second
    assert len(first) == 2


def test_search_definition_and_strategies_validate_inputs() -> None:
    with pytest.raises(DomainValidationError, match="cannot be empty"):
        ModelSearchDefinition.create(
            name="ridge",
            version="1",
            family=ModelFamily.LINEAR,
            task=LearningTask.REGRESSION,
            plugin_key="linear.ridge",
            parameter_grid={"alpha": ()},
        )
    with pytest.raises(DomainValidationError, match="required"):
        ModelSearchDefinition("", "1", ModelFamily.LINEAR, LearningTask.REGRESSION, "x")
    with pytest.raises(DomainValidationError, match="invalid"):
        GridSearchStrategy().candidates(definitions(), random_seed=-1, maximum_trials=1)
    with pytest.raises(DomainValidationError, match="positive"):
        RandomSearchStrategy().candidates(definitions(), random_seed=1, maximum_trials=0)
