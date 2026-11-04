"""Health and service-level objective evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import SloSnapshotId
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal

_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    component: str
    state: HealthState
    checked_at: UtcInstant
    detail: str
    latency_milliseconds: Decimal

    def __init__(
        self,
        component: str,
        state: HealthState,
        checked_at: UtcInstant,
        detail: str,
        latency_milliseconds: DecimalInput,
    ) -> None:
        name = component.strip().lower()
        message = detail.strip()
        latency = to_decimal(latency_milliseconds, field_name="health latency")
        if not _NAME.fullmatch(name) or not message or latency < 0:
            raise DomainValidationError("Health check evidence is invalid")
        object.__setattr__(self, "component", name)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "detail", message)
        object.__setattr__(self, "latency_milliseconds", latency)


class SloIndicator(StrEnum):
    AVAILABILITY = "availability"
    LATENCY = "latency"
    FRESHNESS = "freshness"


@dataclass(frozen=True, slots=True)
class ServiceLevelObjective:
    name: str
    indicator: SloIndicator
    target: Decimal
    window_seconds: int
    latency_threshold_milliseconds: Decimal | None = None

    def __init__(
        self,
        name: str,
        indicator: SloIndicator,
        target: DecimalInput,
        window_seconds: int,
        latency_threshold_milliseconds: DecimalInput | None = None,
    ) -> None:
        normalized = name.strip().lower()
        target_value = to_decimal(target, field_name="SLO target")
        latency = (
            to_decimal(
                latency_threshold_milliseconds,
                field_name="SLO latency threshold",
            )
            if latency_threshold_milliseconds is not None
            else None
        )
        if not _NAME.fullmatch(normalized) or not Decimal(0) < target_value <= Decimal(1):
            raise DomainValidationError("SLO name or target is invalid")
        if window_seconds <= 0:
            raise DomainValidationError("SLO window must be positive")
        if indicator is SloIndicator.LATENCY and (latency is None or latency <= 0):
            raise DomainValidationError("SLO latency threshold must be positive")
        if indicator is not SloIndicator.LATENCY and latency is not None:
            raise DomainValidationError("Only latency SLOs accept a latency threshold")
        object.__setattr__(self, "name", normalized)
        object.__setattr__(self, "indicator", indicator)
        object.__setattr__(self, "target", target_value)
        object.__setattr__(self, "window_seconds", window_seconds)
        object.__setattr__(self, "latency_threshold_milliseconds", latency)


@dataclass(frozen=True, slots=True)
class SloSnapshot:
    snapshot_id: SloSnapshotId
    objective: ServiceLevelObjective
    window: InstantInterval
    total_events: int
    good_events: int
    measured_value: Decimal
    error_budget_remaining: Decimal
    state: HealthState
    created_at: UtcInstant
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.total_events <= 0 or not 0 <= self.good_events <= self.total_events:
            raise DomainValidationError("SLO event counts are invalid")
        if not Decimal(0) <= self.measured_value <= Decimal(1):
            raise DomainValidationError("SLO measured value must be a fraction")
        if not Decimal(-1) <= self.error_budget_remaining <= Decimal(1):
            raise DomainValidationError("SLO error budget must be bounded")
        if self.created_at < self.window.end:
            raise DomainValidationError("SLO snapshot cannot predate its window")
        payload = {
            "snapshot_id": str(self.snapshot_id),
            "objective": self.objective.name,
            "indicator": self.objective.indicator.value,
            "target": str(self.objective.target),
            "window": (self.window.start.isoformat(), self.window.end.isoformat()),
            "total_events": self.total_events,
            "good_events": self.good_events,
            "measured_value": str(self.measured_value),
            "error_budget_remaining": str(self.error_budget_remaining),
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())
