from dataclasses import replace
from datetime import date

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.modeling.splits import (
    DatasetSplitPlan,
    TimeSeriesFold,
    WalkForwardSplitConfig,
)
from tests.helpers.modeling import make_dataset


def test_walk_forward_config_has_stable_fingerprint() -> None:
    config = WalkForwardSplitConfig(
        minimum_train_periods=5,
        validation_periods=2,
        step_periods=2,
        final_holdout_periods=3,
        gap_periods=1,
        embargo_periods=1,
        maximum_train_periods=10,
    )
    assert len(config.fingerprint) == 64
    assert config.fingerprint == replace(config).fingerprint


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"minimum_train_periods": 0}, "positive"),
        ({"gap_periods": -1}, "cannot be negative"),
        ({"maximum_train_periods": 2}, "cannot be below"),
    ],
)
def test_walk_forward_config_rejects_invalid_periods(kwargs, message) -> None:
    values = {
        "minimum_train_periods": 5,
        "validation_periods": 2,
        "step_periods": 1,
        "final_holdout_periods": 2,
    }
    values.update(kwargs)
    with pytest.raises(DomainValidationError, match=message):
        WalkForwardSplitConfig(**values)


def test_fold_and_plan_validate_disjoint_boundaries() -> None:
    dataset = make_dataset(periods=10)
    fold = TimeSeriesFold(
        fold_number=1,
        train_indices=(0, 1, 2),
        validation_indices=(4, 5),
        purged_indices=(3,),
        train_start=date(2025, 1, 2),
        train_end=date(2025, 1, 4),
        validation_start=date(2025, 1, 6),
        validation_end=date(2025, 1, 7),
    )
    plan = DatasetSplitPlan(
        dataset.dataset_version_id,
        WalkForwardSplitConfig(3, 2, 1, 2),
        (fold,),
        development_indices=(0, 1, 2, 3, 4, 5, 6, 7),
        holdout_indices=(8, 9),
        excluded_indices=(),
    )
    assert len(fold.fingerprint) == 64
    assert len(plan.fingerprint) == 64

    with pytest.raises(DomainValidationError, match="cannot overlap"):
        replace(fold, validation_indices=(2, 3))
    with pytest.raises(DomainValidationError, match="Purged rows"):
        replace(fold, purged_indices=(0,))
    with pytest.raises(DomainValidationError, match="walk-forward"):
        replace(fold, validation_start=date(2025, 1, 3))
    with pytest.raises(DomainValidationError, match="disjoint"):
        replace(plan, excluded_indices=(8,))
    with pytest.raises(DomainValidationError, match="development rows only"):
        replace(plan, development_indices=(0, 1, 2, 3))
