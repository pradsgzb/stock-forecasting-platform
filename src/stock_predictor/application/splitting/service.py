"""Purged walk-forward validation with an untouched final holdout."""

from __future__ import annotations

from stock_predictor.domain.common.errors import DatasetSplitError
from stock_predictor.domain.modeling.datasets import DatasetSnapshot
from stock_predictor.domain.modeling.splits import (
    DatasetSplitPlan,
    TimeSeriesFold,
    WalkForwardSplitConfig,
)


class PurgedWalkForwardSplitter:
    """Creates chronological folds and removes labels crossing validation boundaries."""

    def split(
        self,
        dataset: DatasetSnapshot,
        config: WalkForwardSplitConfig,
    ) -> DatasetSplitPlan:
        all_dates = tuple(sorted({item.as_of for item in dataset.rows}))
        required = (
            config.minimum_train_periods
            + config.gap_periods
            + config.validation_periods
            + config.embargo_periods
            + config.final_holdout_periods
        )
        if len(all_dates) < required:
            raise DatasetSplitError(
                f"Dataset has {len(all_dates)} periods but split requires at least {required}"
            )
        holdout_dates = all_dates[-config.final_holdout_periods :]
        holdout_start = holdout_dates[0]
        pre_holdout_dates = all_dates[: -config.final_holdout_periods]
        embargo_dates = (
            pre_holdout_dates[-config.embargo_periods :]
            if config.embargo_periods
            else ()
        )
        embargo_set = set(embargo_dates)
        holdout_set = set(holdout_dates)
        holdout_indices = tuple(
            index
            for index, row in enumerate(dataset.rows)
            if row.as_of in holdout_set
        )
        excluded_indices = tuple(
            index
            for index, row in enumerate(dataset.rows)
            if row.as_of in embargo_set
            or (row.as_of < holdout_start and row.label_end_date >= holdout_start)
        )
        excluded_set = set(excluded_indices)
        development_indices = tuple(
            index
            for index, row in enumerate(dataset.rows)
            if row.as_of < holdout_start and index not in excluded_set
        )
        if not development_indices or not holdout_indices:
            raise DatasetSplitError("Holdout isolation removed development or holdout rows")
        development_dates = tuple(
            sorted({dataset.rows[index].as_of for index in development_indices})
        )
        folds: list[TimeSeriesFold] = []
        validation_start_position = config.minimum_train_periods + config.gap_periods
        fold_number = 1
        while validation_start_position + config.validation_periods <= len(
            development_dates
        ):
            validation_dates = development_dates[
                validation_start_position : validation_start_position
                + config.validation_periods
            ]
            validation_start = validation_dates[0]
            candidate_end = validation_start_position - config.gap_periods
            candidate_dates = development_dates[:candidate_end]
            if config.maximum_train_periods is not None:
                candidate_dates = candidate_dates[-config.maximum_train_periods :]
            candidate_set = set(candidate_dates)
            validation_set = set(validation_dates)
            candidate_indices = tuple(
                index
                for index in development_indices
                if dataset.rows[index].as_of in candidate_set
            )
            overlap_purged = tuple(
                index
                for index in candidate_indices
                if dataset.rows[index].label_end_date >= validation_start
            )
            overlap_set = set(overlap_purged)
            train_indices = tuple(
                index for index in candidate_indices if index not in overlap_set
            )
            validation_indices = tuple(
                index
                for index in development_indices
                if dataset.rows[index].as_of in validation_set
            )
            gap_dates = set(
                development_dates[candidate_end:validation_start_position]
            )
            gap_indices = tuple(
                index
                for index in development_indices
                if dataset.rows[index].as_of in gap_dates
            )
            purged_indices = tuple(sorted((*overlap_purged, *gap_indices)))
            if not train_indices or not validation_indices:
                raise DatasetSplitError(
                    f"Fold {fold_number} has no training or validation rows after purging"
                )
            train_dates = tuple(dataset.rows[index].as_of for index in train_indices)
            if len(set(train_dates)) < config.minimum_train_periods:
                raise DatasetSplitError(
                    f"Fold {fold_number} has fewer than the required training periods"
                )
            if any(
                dataset.rows[index].label_end_date >= validation_start
                for index in train_indices
            ):
                raise DatasetSplitError("Purging failed to remove overlapping labels")
            folds.append(
                TimeSeriesFold(
                    fold_number=fold_number,
                    train_indices=train_indices,
                    validation_indices=validation_indices,
                    purged_indices=purged_indices,
                    train_start=min(train_dates),
                    train_end=max(train_dates),
                    validation_start=validation_start,
                    validation_end=validation_dates[-1],
                )
            )
            fold_number += 1
            validation_start_position += config.step_periods
        if not folds:
            raise DatasetSplitError("Split configuration produced no validation folds")
        return DatasetSplitPlan(
            dataset_version_id=dataset.dataset_version_id,
            config=config,
            folds=tuple(folds),
            development_indices=development_indices,
            holdout_indices=holdout_indices,
            excluded_indices=excluded_indices,
        )
