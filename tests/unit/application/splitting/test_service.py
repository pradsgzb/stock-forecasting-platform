import pytest

from stock_predictor.application.splitting.service import PurgedWalkForwardSplitter
from stock_predictor.domain.common.errors import DatasetSplitError
from stock_predictor.domain.modeling.splits import WalkForwardSplitConfig
from tests.helpers.modeling import make_dataset


def test_purged_walk_forward_creates_folds_and_untouched_holdout() -> None:
    dataset = make_dataset(periods=24, label_horizon_days=2)
    config = WalkForwardSplitConfig(
        minimum_train_periods=5,
        validation_periods=3,
        step_periods=3,
        final_holdout_periods=4,
        gap_periods=2,
        embargo_periods=1,
        maximum_train_periods=8,
    )

    plan = PurgedWalkForwardSplitter().split(dataset, config)

    assert len(plan.folds) >= 2
    assert set(plan.development_indices).isdisjoint(plan.holdout_indices)
    assert set(plan.excluded_indices).isdisjoint(plan.holdout_indices)
    for fold in plan.folds:
        validation_start = fold.validation_start
        assert all(
            dataset.rows[index].label_end_date < validation_start
            for index in fold.train_indices
        )
        assert max(dataset.rows[index].as_of for index in fold.train_indices) < validation_start


def test_splitter_rejects_small_dataset_and_empty_post_purge_train() -> None:
    small = make_dataset(periods=5)
    with pytest.raises(DatasetSplitError, match="requires at least"):
        PurgedWalkForwardSplitter().split(
            small,
            WalkForwardSplitConfig(3, 1, 1, 2),
        )

    overlapping = make_dataset(periods=12, label_horizon_days=20)
    with pytest.raises(DatasetSplitError, match="Holdout isolation"):
        PurgedWalkForwardSplitter().split(
            overlapping,
            WalkForwardSplitConfig(3, 2, 1, 2),
        )
