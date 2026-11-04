"""Immutable supervised-learning datasets and row-level lineage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    DatasetRowId,
    DatasetVersionId,
    FeatureSetVersionId,
    FeatureSnapshotId,
    InstrumentId,
    LabelId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal
from stock_predictor.domain.modeling.targets import TargetDefinition, TargetValueType


def _normalize_sha256(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    invalid_character = any(
        character not in "0123456789abcdef" for character in normalized
    )
    if len(normalized) != 64 or invalid_character:
        raise DomainValidationError(f"{field_name} must be a SHA-256 fingerprint")
    return normalized


class MissingLabelAction(StrEnum):
    """Dataset handling when a future outcome cannot be calculated."""

    DROP_ROW = "drop_row"
    FAIL = "fail"


class MissingFeatureAction(StrEnum):
    """Dataset-level handling for missing materialized feature values."""

    DROP_ROW = "drop_row"
    FAIL = "fail"
    IMPUTE_ZERO = "impute_zero"


@dataclass(frozen=True, slots=True)
class DatasetBuildPolicy:
    """Versioned handling policy for dataset materialization."""

    version: str = "1.0.0"
    missing_feature_action: MissingFeatureAction = MissingFeatureAction.DROP_ROW
    missing_label_action: MissingLabelAction = MissingLabelAction.DROP_ROW
    adjusted_features: bool = True

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise DomainValidationError("Dataset build-policy version is required")

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "missing_feature_action": self.missing_feature_action.value,
                "missing_label_action": self.missing_label_action.value,
                "adjusted_features": self.adjusted_features,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class DatasetBuildPoint:
    """One requested point-in-time sample before feature and label materialization."""

    instrument_id: InstrumentId
    as_of: date
    decision_cutoff: UtcInstant
    outcome_cutoff: UtcInstant
    sample_weight: Decimal = Decimal(1)

    def __init__(
        self,
        instrument_id: InstrumentId,
        as_of: date,
        decision_cutoff: UtcInstant,
        outcome_cutoff: UtcInstant,
        sample_weight: DecimalInput = Decimal(1),
    ) -> None:
        weight = to_decimal(sample_weight, field_name="sample weight")
        if outcome_cutoff <= decision_cutoff:
            raise DomainValidationError(
                "Outcome cutoff must be later than the feature decision cutoff"
            )
        if weight <= 0:
            raise DomainValidationError("Sample weight must be positive")
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "decision_cutoff", decision_cutoff)
        object.__setattr__(self, "outcome_cutoff", outcome_cutoff)
        object.__setattr__(self, "sample_weight", weight)


@dataclass(frozen=True, slots=True)
class DatasetRow:
    """One immutable, fully numeric model row with source references."""

    row_id: DatasetRowId
    instrument_id: InstrumentId
    as_of: date
    decision_cutoff: UtcInstant
    feature_keys: tuple[str, ...]
    feature_values: tuple[Decimal, ...]
    target_key: str
    target_value: Decimal | int
    label_end_date: date
    label_available_at: UtcInstant
    sample_weight: Decimal
    source_feature_snapshot_id: FeatureSnapshotId
    source_label_id: LabelId
    source_feature_fingerprint: str
    source_label_fingerprint: str
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.feature_keys or len(self.feature_keys) != len(self.feature_values):
            raise DomainValidationError("Dataset row features are empty or misaligned")
        if len(set(self.feature_keys)) != len(self.feature_keys):
            raise DomainValidationError("Dataset row feature keys must be unique")
        if not self.target_key.strip():
            raise DomainValidationError("Dataset row target key is required")
        if isinstance(self.target_value, bool):
            raise DomainValidationError("Dataset target values cannot contain bool")
        if self.label_end_date <= self.as_of:
            raise DomainValidationError("Dataset label end must be later than as-of date")
        if self.label_available_at <= self.decision_cutoff:
            raise DomainValidationError(
                "Training labels must become available after the decision cutoff"
            )
        if self.sample_weight <= 0:
            raise DomainValidationError("Dataset sample weight must be positive")
        source_feature_fingerprint = _normalize_sha256(
            self.source_feature_fingerprint,
            field_name="Source feature fingerprint",
        )
        source_label_fingerprint = _normalize_sha256(
            self.source_label_fingerprint,
            field_name="Source label fingerprint",
        )
        object.__setattr__(
            self,
            "source_feature_fingerprint",
            source_feature_fingerprint,
        )
        object.__setattr__(
            self,
            "source_label_fingerprint",
            source_label_fingerprint,
        )
        payload = "|".join(
            (
                str(self.instrument_id),
                self.as_of.isoformat(),
                self.decision_cutoff.isoformat(),
                *(f"{key}:{value}" for key, value in zip(self.feature_keys, self.feature_values)),
                self.target_key,
                str(self.target_value),
                self.label_end_date.isoformat(),
                self.label_available_at.isoformat(),
                str(self.sample_weight),
                self.source_feature_fingerprint,
                self.source_label_fingerprint,
            )
        ).encode("utf-8")
        object.__setattr__(self, "fingerprint", hashlib.sha256(payload).hexdigest())


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """Versioned dataset whose rows, schema, and build policy cannot be mutated."""

    dataset_version_id: DatasetVersionId
    name: str
    feature_set_version_id: FeatureSetVersionId
    feature_set_fingerprint: str
    target: TargetDefinition
    rows: tuple[DatasetRow, ...]
    created_at: UtcInstant
    build_policy: str
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        name = self.name.strip()
        policy = self.build_policy.strip()
        feature_set_fingerprint = _normalize_sha256(
            self.feature_set_fingerprint,
            field_name="Feature-set fingerprint",
        )
        if not name or not policy:
            raise DomainValidationError("Dataset name and build policy are required")
        if not self.rows:
            raise DomainValidationError("Dataset snapshot must contain at least one row")
        first = self.rows[0]
        if any(item.feature_keys != first.feature_keys for item in self.rows):
            raise DomainValidationError("Dataset rows must share one feature schema")
        if any(item.target_key != self.target.key for item in self.rows):
            raise DomainValidationError("Dataset rows must match the target definition")
        row_keys = tuple((item.instrument_id, item.as_of) for item in self.rows)
        if len(set(row_keys)) != len(row_keys):
            raise DomainValidationError(
                "Dataset may contain only one row per instrument and as-of date"
            )
        if self.target.value_type is TargetValueType.BINARY and any(
            item.target_value not in {0, 1} for item in self.rows
        ):
            raise DomainValidationError("Binary datasets may contain only 0/1 labels")
        ordered = tuple(
            sorted(self.rows, key=lambda item: (item.as_of, str(item.instrument_id)))
        )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "feature_set_fingerprint", feature_set_fingerprint)
        object.__setattr__(self, "build_policy", policy)
        object.__setattr__(self, "rows", ordered)
        payload = {
            "name": name,
            "feature_set_version_id": str(self.feature_set_version_id),
            "feature_set_fingerprint": self.feature_set_fingerprint,
            "target_fingerprint": self.target.fingerprint,
            "rows": [item.fingerprint for item in ordered],
            "build_policy": policy,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    @property
    def feature_keys(self) -> tuple[str, ...]:
        return self.rows[0].feature_keys

    @property
    def row_count(self) -> int:
        return len(self.rows)
