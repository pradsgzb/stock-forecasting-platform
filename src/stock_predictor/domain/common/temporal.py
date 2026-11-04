"""Canonical temporal types and effective-period semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError


@dataclass(frozen=True, slots=True, order=True)
class UtcInstant:
    """Timezone-aware instant normalized to UTC."""

    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            msg = "UtcInstant requires a timezone-aware datetime"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", self.value.astimezone(UTC))

    @classmethod
    def parse(cls, raw: str) -> UtcInstant:
        """Parse an ISO-8601 instant, accepting a trailing `Z`."""
        normalized = raw.strip()
        if normalized.endswith(("Z", "z")):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            return cls(datetime.fromisoformat(normalized))
        except ValueError as exc:
            msg = f"Invalid ISO-8601 instant: {raw!r}"
            raise DomainValidationError(msg) from exc

    def plus(self, delta: timedelta) -> UtcInstant:
        """Return a new instant offset by `delta`."""
        return UtcInstant(self.value + delta)

    def isoformat(self) -> str:
        """Render a stable UTC representation."""
        return self.value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class EffectivePeriod:
    """Date interval using inclusive-start and exclusive-end semantics: `[start, end)`."""

    start: date
    end: date | None = None

    def __post_init__(self) -> None:
        if self.end is not None and self.end <= self.start:
            msg = "Effective period end must be later than start"
            raise DomainValidationError(msg)

    def contains(self, candidate: date) -> bool:
        """Return whether `candidate` falls within the interval."""
        return candidate >= self.start and (self.end is None or candidate < self.end)

    def overlaps(self, other: EffectivePeriod) -> bool:
        """Return whether two half-open intervals overlap."""
        self_end = self.end or date.max
        other_end = other.end or date.max
        return self.start < other_end and other.start < self_end


@dataclass(frozen=True, slots=True)
class InstantInterval:
    """Instant interval with inclusive start and exclusive end."""

    start: UtcInstant
    end: UtcInstant

    def __post_init__(self) -> None:
        if self.end <= self.start:
            msg = "Instant interval end must be later than start"
            raise DomainValidationError(msg)

    def contains(self, candidate: UtcInstant) -> bool:
        return self.start <= candidate < self.end

    def overlaps(self, other: InstantInterval) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True, slots=True)
class InformationTimeline:
    """Provenance timeline used to prove when information became usable."""

    event_time: UtcInstant
    published_at: UtcInstant
    received_at: UtcInstant
    processed_at: UtcInstant

    def __post_init__(self) -> None:
        if not (
            self.event_time <= self.published_at <= self.received_at <= self.processed_at
        ):
            msg = (
                "Information timeline must satisfy event <= publication <= receipt <= processing"
            )
            raise DomainValidationError(msg)

    def available_by(self, cutoff: UtcInstant) -> bool:
        """Return whether processing completed no later than `cutoff`."""
        return self.processed_at <= cutoff


class HorizonUnit(StrEnum):
    """Units supported by a prediction horizon."""

    TRADING_SESSIONS = "trading_sessions"
    CALENDAR_DAYS = "calendar_days"
    MINUTES = "minutes"


@dataclass(frozen=True, slots=True)
class PredictionHorizon:
    """Explicit prediction horizon; trading sessions are not calendar days."""

    amount: int
    unit: HorizonUnit

    def __post_init__(self) -> None:
        if self.amount <= 0:
            msg = "Prediction horizon amount must be positive"
            raise DomainValidationError(msg)
