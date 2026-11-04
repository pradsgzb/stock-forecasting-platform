"""Leakage-resistant walk-forward split definitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import DatasetVersionId


@dataclass(frozen=True, slots=True)
class WalkForwardSplitConfig:
    """Configuration for expanding or rolling purged walk-forward validation."""

    minimum_train_periods: int
    validation_periods: int
    step_periods: int
    final_holdout_periods: int
    gap_periods: int = 0
    embargo_periods: int = 0
    maximum_train_periods: int | None = None

    def __post_init__(self) -> None:
        positive = (
            self.minimum_train_periods,
            self.validation_periods,
            self.step_periods,
            self.final_holdout_periods,
        )
        if any(value <= 0 for value in positive):
            raise DomainValidationError("Core split periods must be positive")
        if self.gap_periods < 0 or self.embargo_periods < 0:
            raise DomainValidationError("Gap and embargo periods cannot be negative")
        if (
            self.maximum_train_periods is not None
            and self.maximum_train_periods < self.minimum_train_periods
        ):
            raise DomainValidationError(
                "Maximum training periods cannot be below minimum training periods"
            )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "minimum_train_periods": self.minimum_train_periods,
                "validation_periods": self.validation_periods,
                "step_periods": self.step_periods,
                "final_holdout_periods": self.final_holdout_periods,
                "gap_periods": self.gap_periods,
                "embargo_periods": self.embargo_periods,
                "maximum_train_periods": self.maximum_train_periods,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class TimeSeriesFold:
    """One validation fold containing only earlier, non-overlapping training labels."""

    fold_number: int
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    purged_indices: tuple[int, ...]
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.fold_number <= 0:
            raise DomainValidationError("Fold number must be positive")
        if not self.train_indices or not self.validation_indices:
            raise DomainValidationError("Every fold requires training and validation rows")
        groups = (self.train_indices, self.validation_indices, self.purged_indices)
        if any(len(set(group)) != len(group) for group in groups):
            raise DomainValidationError("Fold index groups cannot contain duplicates")
        if set(self.train_indices) & set(self.validation_indices):
            raise DomainValidationError("Training and validation indices cannot overlap")
        if set(self.purged_indices) & (
            set(self.train_indices) | set(self.validation_indices)
        ):
            raise DomainValidationError("Purged rows cannot remain in a fold")
        if not (
            self.train_start <= self.train_end < self.validation_start <= self.validation_end
        ):
            raise DomainValidationError("Fold dates are not strictly walk-forward")
        payload = "|".join(
            (
                str(self.fold_number),
                ",".join(str(item) for item in self.train_indices),
                ",".join(str(item) for item in self.validation_indices),
                ",".join(str(item) for item in self.purged_indices),
                self.train_start.isoformat(),
                self.train_end.isoformat(),
                self.validation_start.isoformat(),
                self.validation_end.isoformat(),
            )
        ).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(payload).hexdigest())


@dataclass(frozen=True, slots=True)
class DatasetSplitPlan:
    """Immutable cross-validation and final-holdout partition plan."""

    dataset_version_id: DatasetVersionId
    config: WalkForwardSplitConfig
    folds: tuple[TimeSeriesFold, ...]
    development_indices: tuple[int, ...]
    holdout_indices: tuple[int, ...]
    excluded_indices: tuple[int, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.folds:
            raise DomainValidationError("Split plan requires at least one validation fold")
        if not self.development_indices or not self.holdout_indices:
            raise DomainValidationError("Split plan requires development and holdout rows")
        all_groups = (
            self.development_indices,
            self.holdout_indices,
            self.excluded_indices,
        )
        if any(len(set(group)) != len(group) for group in all_groups):
            raise DomainValidationError("Split-plan index groups cannot contain duplicates")
        development = set(self.development_indices)
        holdout = set(self.holdout_indices)
        excluded = set(self.excluded_indices)
        if development & holdout or development & excluded or holdout & excluded:
            raise DomainValidationError("Split-plan index groups must be disjoint")
        if any(
            not set(fold.train_indices).issubset(development)
            or not set(fold.validation_indices).issubset(development)
            for fold in self.folds
        ):
            raise DomainValidationError("Cross-validation folds must use development rows only")
        payload = {
            "dataset_version_id": str(self.dataset_version_id),
            "config": self.config.fingerprint,
            "folds": [item.fingerprint for item in self.folds],
            "development_indices": self.development_indices,
            "holdout_indices": self.holdout_indices,
            "excluded_indices": self.excluded_indices,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())
