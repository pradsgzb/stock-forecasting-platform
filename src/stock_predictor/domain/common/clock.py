"""Clock abstractions for deterministic time-dependent behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from stock_predictor.domain.common.temporal import UtcInstant


class Clock(Protocol):
    """Provides the current instant without coupling business logic to wall-clock time."""

    def now(self) -> UtcInstant:
        """Return the current UTC instant."""
        ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Production clock backed by the operating system."""

    def now(self) -> UtcInstant:
        return UtcInstant(datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Deterministic clock useful for tests and repeatable simulations."""

    instant: UtcInstant

    def now(self) -> UtcInstant:
        return self.instant
