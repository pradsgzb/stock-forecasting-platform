"""Port for exchange trading calendars."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.calendar import TradingSession
from stock_predictor.domain.market.identifiers import MarketIdentifierCode


@runtime_checkable
class CalendarProvider(Protocol):
    """Provides authoritative regular-session schedules for configured exchanges."""

    def is_session(self, mic: MarketIdentifierCode, session_date: date) -> bool:
        """Return whether `session_date` is a regular session label."""
        ...

    def session(self, mic: MarketIdentifierCode, session_date: date) -> TradingSession:
        """Return a session or raise `NonTradingDayError`."""
        ...

    def session_or_none(
        self,
        mic: MarketIdentifierCode,
        session_date: date,
    ) -> TradingSession | None:
        """Return a session or `None` for a non-trading date."""
        ...

    def sessions(
        self,
        mic: MarketIdentifierCode,
        start: date,
        end: date,
    ) -> tuple[TradingSession, ...]:
        """Return sessions with labels in the inclusive date range."""
        ...

    def next_session(self, mic: MarketIdentifierCode, after: date) -> TradingSession:
        """Return the first session strictly after `after`."""
        ...

    def previous_session(self, mic: MarketIdentifierCode, before: date) -> TradingSession:
        """Return the first session strictly before `before`."""
        ...

    def session_containing(
        self,
        mic: MarketIdentifierCode,
        instant: UtcInstant,
    ) -> TradingSession | None:
        """Return the session whose open-to-close interval contains `instant`."""
        ...
