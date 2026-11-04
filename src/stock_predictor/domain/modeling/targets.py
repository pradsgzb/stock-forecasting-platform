"""Versioned prediction targets and immutable realized labels."""

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
    InstrumentId,
    LabelId,
    PriceBarId,
    TargetDefinitionId,
)
from stock_predictor.domain.common.temporal import (
    HorizonUnit,
    PredictionHorizon,
    UtcInstant,
)
from stock_predictor.domain.common.values import DecimalInput, to_decimal

_TARGET_NAME = re.compile(r"^[a-z][a-z0-9_]{1,127}$")


class TargetKind(StrEnum):
    """Supported daily-equity supervised-learning targets."""

    SIMPLE_RETURN = "simple_return"
    LOG_RETURN = "log_return"
    DIRECTION = "direction"
    REALIZED_VOLATILITY = "realized_volatility"
    RELATIVE_RETURN = "relative_return"
    CROSS_SECTIONAL_RANK = "cross_sectional_rank"
    MAX_ADVERSE_EXCURSION = "max_adverse_excursion"
    MAX_FAVORABLE_EXCURSION = "max_favorable_excursion"


class TargetValueType(StrEnum):
    """Machine-learning value shape produced by a target."""

    CONTINUOUS = "continuous"
    BINARY = "binary"


@dataclass(frozen=True, slots=True)
class TargetDefinition:
    """Immutable and fingerprinted label-generation contract."""

    target_definition_id: TargetDefinitionId
    name: str
    version: str
    kind: TargetKind
    horizon: PredictionHorizon
    positive_threshold: Decimal = Decimal(0)
    annualization_sessions: int = 252
    benchmark_instrument_id: InstrumentId | None = None
    fingerprint: str = field(init=False)

    def __init__(
        self,
        target_definition_id: TargetDefinitionId,
        name: str,
        version: str,
        kind: TargetKind,
        horizon: PredictionHorizon,
        *,
        positive_threshold: DecimalInput = Decimal(0),
        annualization_sessions: int = 252,
        benchmark_instrument_id: InstrumentId | None = None,
    ) -> None:
        normalized_name = name.strip().lower()
        normalized_version = version.strip()
        threshold = to_decimal(positive_threshold, field_name="positive threshold")
        if not _TARGET_NAME.fullmatch(normalized_name):
            raise DomainValidationError(f"Invalid target name: {name!r}")
        if not normalized_version:
            raise DomainValidationError("Target version is required")
        if horizon.unit is not HorizonUnit.TRADING_SESSIONS:
            raise DomainValidationError(
                "The daily target engine currently supports trading-session horizons only"
            )
        if kind is TargetKind.REALIZED_VOLATILITY and horizon.amount < 2:
            raise DomainValidationError(
                "Realized-volatility targets require at least two trading sessions"
            )
        if annualization_sessions <= 0:
            raise DomainValidationError("Annualization sessions must be positive")
        if kind is TargetKind.RELATIVE_RETURN and benchmark_instrument_id is None:
            raise DomainValidationError("Relative-return targets require a benchmark")
        if kind is not TargetKind.RELATIVE_RETURN and benchmark_instrument_id is not None:
            raise DomainValidationError(
                "A benchmark is only valid for relative-return targets"
            )
        object.__setattr__(self, "target_definition_id", target_definition_id)
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "version", normalized_version)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "positive_threshold", threshold)
        object.__setattr__(self, "annualization_sessions", annualization_sessions)
        object.__setattr__(self, "benchmark_instrument_id", benchmark_instrument_id)
        payload = {
            "id": str(target_definition_id),
            "name": normalized_name,
            "version": normalized_version,
            "kind": kind.value,
            "horizon": {"amount": horizon.amount, "unit": horizon.unit.value},
            "positive_threshold": str(threshold),
            "annualization_sessions": annualization_sessions,
            "benchmark_instrument_id": (
                str(benchmark_instrument_id)
                if benchmark_instrument_id is not None
                else None
            ),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def value_type(self) -> TargetValueType:
        if self.kind is TargetKind.DIRECTION:
            return TargetValueType.BINARY
        return TargetValueType.CONTINUOUS


@dataclass(frozen=True, slots=True)
class LabelObservation:
    """One immutable target value with exact availability and source lineage."""

    label_id: LabelId
    target: TargetDefinition
    instrument_id: InstrumentId
    as_of: date
    horizon_end: date
    outcome_cutoff: UtcInstant
    available_at: UtcInstant
    value: Decimal | int | None
    missing_reason: str | None
    source_bar_ids: tuple[PriceBarId, ...]
    fingerprint: str = field(init=False)

    def __init__(
        self,
        label_id: LabelId,
        target: TargetDefinition,
        instrument_id: InstrumentId,
        as_of: date,
        horizon_end: date,
        outcome_cutoff: UtcInstant,
        available_at: UtcInstant,
        value: DecimalInput | int | None,
        missing_reason: str | None,
        source_bar_ids: tuple[PriceBarId, ...],
    ) -> None:
        if horizon_end <= as_of:
            raise DomainValidationError("Label horizon end must be later than as-of date")
        if available_at > outcome_cutoff:
            raise DomainValidationError("Label cannot be available after its outcome cutoff")
        normalized_reason = missing_reason.strip() if missing_reason is not None else None
        if value is None and not normalized_reason:
            raise DomainValidationError("Missing label values require a reason")
        if value is not None and normalized_reason is not None:
            raise DomainValidationError("Present label values cannot carry a missing reason")
        normalized_value: Decimal | int | None
        if value is None:
            normalized_value = None
        elif target.value_type is TargetValueType.BINARY:
            if isinstance(value, bool):
                normalized_value = int(value)
            elif isinstance(value, int) and value in {0, 1}:
                normalized_value = value
            else:
                raise DomainValidationError("Binary labels must be 0 or 1")
        else:
            if isinstance(value, bool):
                raise DomainValidationError("Continuous labels cannot contain bool values")
            normalized_value = to_decimal(value, field_name=f"label {target.key}")
        if len(set(source_bar_ids)) != len(source_bar_ids):
            raise DomainValidationError("Label source bars must be unique")
        object.__setattr__(self, "label_id", label_id)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "horizon_end", horizon_end)
        object.__setattr__(self, "outcome_cutoff", outcome_cutoff)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "value", normalized_value)
        object.__setattr__(self, "missing_reason", normalized_reason)
        object.__setattr__(self, "source_bar_ids", source_bar_ids)
        payload = "|".join(
            (
                target.fingerprint,
                str(instrument_id),
                as_of.isoformat(),
                horizon_end.isoformat(),
                outcome_cutoff.isoformat(),
                available_at.isoformat(),
                str(normalized_value),
                str(normalized_reason),
                *(str(item) for item in source_bar_ids),
            )
        ).encode("utf-8")
        object.__setattr__(self, "fingerprint", hashlib.sha256(payload).hexdigest())

    @property
    def is_missing(self) -> bool:
        return self.value is None
