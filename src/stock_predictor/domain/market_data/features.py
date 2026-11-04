"""Versioned feature definitions, sets, observations, and snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    FeatureSetVersionId,
    FeatureSnapshotId,
    InstrumentId,
    PriceBarId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal

_FEATURE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class FeatureInputBar:
    """Leakage-checked, optionally adjusted numeric view consumed by feature calculators."""

    bar_id: PriceBarId
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    available_at: UtcInstant
    source_fingerprint: str

    def __post_init__(self) -> None:
        prices = (self.open_price, self.high_price, self.low_price, self.close_price)
        if any(value <= 0 for value in prices):
            raise DomainValidationError("Feature input prices must be positive")
        if self.volume < 0:
            raise DomainValidationError("Feature input volume cannot be negative")
        if self.low_price > min(self.open_price, self.close_price, self.high_price):
            raise DomainValidationError("Feature input low price is inconsistent")
        if self.high_price < max(self.open_price, self.close_price, self.low_price):
            raise DomainValidationError("Feature input high price is inconsistent")
        normalized_fingerprint = self.source_fingerprint.strip().lower()
        if not _SHA256_PATTERN.fullmatch(normalized_fingerprint):
            raise DomainValidationError("Feature input fingerprint must be SHA-256")
        object.__setattr__(self, "source_fingerprint", normalized_fingerprint)


class FeatureValueType(StrEnum):
    DECIMAL = "decimal"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class MissingValuePolicy(StrEnum):
    RETURN_MISSING = "return_missing"
    FAIL = "fail"
    IMPUTE_ZERO = "impute_zero"


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    version: str
    description: str
    lookback_sessions: int
    minimum_history: int
    value_type: FeatureValueType = FeatureValueType.DECIMAL
    missing_value_policy: MissingValuePolicy = MissingValuePolicy.RETURN_MISSING

    def __post_init__(self) -> None:
        name = self.name.strip().lower()
        version = self.version.strip()
        description = self.description.strip()
        if not _FEATURE_NAME.fullmatch(name):
            raise DomainValidationError(f"Invalid feature name: {self.name!r}")
        if not version or not description:
            raise DomainValidationError("Feature version and description are required")
        if self.lookback_sessions < 0 or self.minimum_history <= 0:
            raise DomainValidationError("Feature history requirements are invalid")
        if self.minimum_history > self.lookback_sessions + 1:
            raise DomainValidationError("Minimum history cannot exceed lookback plus current bar")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "description", description)

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class FeatureSet:
    feature_set_version_id: FeatureSetVersionId
    name: str
    version: str
    definitions: tuple[FeatureDefinition, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        name = self.name.strip()
        version = self.version.strip()
        if not name or not version or not self.definitions:
            raise DomainValidationError("Feature set requires name, version, and definitions")
        keys = tuple(item.key for item in self.definitions)
        if len(set(keys)) != len(keys):
            raise DomainValidationError("Feature definitions must be unique within a feature set")
        ordered = tuple(sorted(self.definitions, key=lambda item: item.key))
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "definitions", ordered)
        payload = {
            "feature_set_version_id": str(self.feature_set_version_id),
            "name": name,
            "version": version,
            "definitions": [
                {
                    "name": item.name,
                    "version": item.version,
                    "description": item.description,
                    "lookback": item.lookback_sessions,
                    "minimum_history": item.minimum_history,
                    "type": item.value_type.value,
                    "missing": item.missing_value_policy.value,
                }
                for item in ordered
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    @property
    def maximum_lookback(self) -> int:
        return max(item.lookback_sessions for item in self.definitions)


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    definition: FeatureDefinition
    value: Decimal | int | bool | None
    missing_reason: str | None
    source_bar_ids: tuple[PriceBarId, ...]

    def __init__(
        self,
        definition: FeatureDefinition,
        value: DecimalInput | int | bool | None,
        missing_reason: str | None,
        source_bar_ids: tuple[PriceBarId, ...],
    ) -> None:
        if value is None and not missing_reason:
            raise DomainValidationError("Missing feature values require a reason")
        if value is not None and missing_reason is not None:
            raise DomainValidationError("Present feature values cannot have a missing reason")
        normalized: Decimal | int | bool | None
        if value is None:
            normalized = None
        elif definition.value_type is FeatureValueType.BOOLEAN:
            if not isinstance(value, bool):
                raise DomainValidationError("Boolean features require bool values")
            normalized = value
        elif isinstance(value, bool):
            raise DomainValidationError("Numeric features cannot contain bool values")
        elif definition.value_type is FeatureValueType.INTEGER:
            decimal_value = to_decimal(value, field_name=f"feature {definition.name}")
            if decimal_value != decimal_value.to_integral_value():
                raise DomainValidationError("Integer feature cannot contain a fractional value")
            normalized = int(decimal_value)
        else:
            normalized = to_decimal(value, field_name=f"feature {definition.name}")
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "value", normalized)
        object.__setattr__(self, "missing_reason", missing_reason)
        object.__setattr__(self, "source_bar_ids", source_bar_ids)


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    snapshot_id: FeatureSnapshotId
    feature_set: FeatureSet
    instrument_id: InstrumentId
    as_of: date
    decision_cutoff: UtcInstant
    generated_at: UtcInstant
    observations: tuple[FeatureObservation, ...]
    input_fingerprint: str
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.generated_at < self.decision_cutoff:
            raise DomainValidationError("Feature generation cannot precede decision cutoff")
        expected = tuple(item.key for item in self.feature_set.definitions)
        actual = tuple(item.definition.key for item in self.observations)
        if actual != expected:
            raise DomainValidationError(
                "Feature snapshot observations must match feature set order"
            )
        normalized_input = self.input_fingerprint.strip().lower()
        if not _SHA256_PATTERN.fullmatch(normalized_input):
            raise DomainValidationError("Feature input fingerprint must be SHA-256")
        object.__setattr__(self, "input_fingerprint", normalized_input)
        payload = "|".join(
            (
                self.feature_set.fingerprint,
                str(self.instrument_id),
                self.as_of.isoformat(),
                self.decision_cutoff.isoformat(),
                self.input_fingerprint,
                *(
                    ":".join(
                        (
                            item.definition.key,
                            str(item.value),
                            str(item.missing_reason),
                            ",".join(str(source_id) for source_id in item.source_bar_ids),
                        )
                    )
                    for item in self.observations
                ),
            )
        ).encode("utf-8")
        object.__setattr__(self, "fingerprint", hashlib.sha256(payload).hexdigest())
