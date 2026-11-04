"""Trading-session domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.market.identifiers import MarketIdentifierCode


class MarketPhase(StrEnum):
    """Regular-session phase at a requested instant."""

    CLOSED = "closed"
    PRE_OPEN = "pre_open"
    OPEN = "open"
    BREAK = "break"
    POST_CLOSE = "post_close"


@dataclass(frozen=True, slots=True)
class TradingBreak:
    """Intraday interval during which regular trading is closed."""

    interval: InstantInterval

    @property
    def starts_at(self) -> UtcInstant:
        return self.interval.start

    @property
    def ends_at(self) -> UtcInstant:
        return self.interval.end

    def contains(self, instant: UtcInstant) -> bool:
        return self.interval.contains(instant)


@dataclass(frozen=True, slots=True)
class TradingSession:
    """Exchange regular-trading session identified by an exchange-local label date."""

    exchange_mic: MarketIdentifierCode
    session_date: date
    opens_at: UtcInstant
    closes_at: UtcInstant
    breaks: tuple[TradingBreak, ...] = ()

    def __post_init__(self) -> None:
        if self.closes_at <= self.opens_at:
            msg = "Trading session close must be later than open"
            raise DomainValidationError(msg)
        ordered = tuple(sorted(self.breaks, key=lambda item: item.starts_at))
        previous_end: UtcInstant | None = None
        for trading_break in ordered:
            if (
                trading_break.starts_at <= self.opens_at
                or trading_break.ends_at >= self.closes_at
            ):
                msg = "Trading break must be strictly inside session open and close"
                raise DomainValidationError(msg)
            if previous_end is not None and trading_break.starts_at < previous_end:
                msg = "Trading breaks cannot overlap"
                raise DomainValidationError(msg)
            previous_end = trading_break.ends_at
        object.__setattr__(self, "breaks", ordered)

    def is_open_at(self, instant: UtcInstant) -> bool:
        """Return whether regular trading is open at `instant`."""
        if not self.opens_at <= instant < self.closes_at:
            return False
        return not any(trading_break.contains(instant) for trading_break in self.breaks)

    def phase_at(self, instant: UtcInstant) -> MarketPhase:
        """Classify an instant relative to this session."""
        if instant < self.opens_at:
            return MarketPhase.PRE_OPEN
        if instant >= self.closes_at:
            return MarketPhase.POST_CLOSE
        if any(trading_break.contains(instant) for trading_break in self.breaks):
            return MarketPhase.BREAK
        return MarketPhase.OPEN

    @property
    def elapsed_duration(self) -> timedelta:
        """Return wall-clock duration from open to close, including breaks."""
        return self.closes_at.value - self.opens_at.value

    @property
    def regular_trading_duration(self) -> timedelta:
        """Return open-to-close duration excluding configured breaks."""
        break_duration = sum(
            (item.ends_at.value - item.starts_at.value for item in self.breaks),
            start=timedelta(),
        )
        return self.elapsed_duration - break_duration
