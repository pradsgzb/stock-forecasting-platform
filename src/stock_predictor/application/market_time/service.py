"""Use cases that combine exchange identity with calendar schedules."""

from __future__ import annotations

from datetime import timedelta

from stock_predictor.domain.common.errors import DomainValidationError, NonTradingDayError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.calendar import MarketPhase, TradingSession
from stock_predictor.domain.market.exchange import ExchangeCatalog
from stock_predictor.domain.market.identifiers import MarketIdentifierCode
from stock_predictor.ports.calendar_provider import CalendarProvider


class MarketTimeService:
    """Answers market-state questions using an explicit exchange calendar port."""

    __slots__ = ("_calendars", "_exchanges")

    def __init__(
        self,
        calendars: CalendarProvider,
        exchanges: ExchangeCatalog,
    ) -> None:
        self._calendars = calendars
        self._exchanges = exchanges

    def phase(self, mic: MarketIdentifierCode, instant: UtcInstant) -> MarketPhase:
        """Return the regular-session phase at an instant."""
        containing = self._calendars.session_containing(mic, instant)
        if containing is not None:
            return containing.phase_at(instant)

        exchange = self._exchanges.get(mic)
        local_date = instant.value.astimezone(exchange.timezone).date()
        same_day = self._calendars.session_or_none(mic, local_date)
        if same_day is None:
            return MarketPhase.CLOSED
        return same_day.phase_at(instant)

    def next_open(self, mic: MarketIdentifierCode, instant: UtcInstant) -> UtcInstant:
        """Return the next regular-session open strictly after `instant`."""
        exchange = self._exchanges.get(mic)
        local_date = instant.value.astimezone(exchange.timezone).date()
        same_day = self._calendars.session_or_none(mic, local_date)
        if same_day is not None and instant < same_day.opens_at:
            return same_day.opens_at
        return self._calendars.next_session(mic, local_date).opens_at

    def session_with_tolerance(
        self,
        mic: MarketIdentifierCode,
        instant: UtcInstant,
        tolerance: timedelta,
    ) -> TradingSession | None:
        """Return the containing session or a recently closed session within tolerance."""
        if tolerance < timedelta():
            msg = "Tolerance cannot be negative"
            raise DomainValidationError(msg)
        containing = self._calendars.session_containing(mic, instant)
        if containing is not None:
            return containing
        exchange = self._exchanges.get(mic)
        local_date = instant.value.astimezone(exchange.timezone).date()
        candidates: list[TradingSession] = []
        same_day = self._calendars.session_or_none(mic, local_date)
        if same_day is not None:
            candidates.append(same_day)
        try:
            previous = self._calendars.previous_session(mic, local_date)
        except NonTradingDayError:
            previous = None
        if previous is not None and previous not in candidates:
            candidates.append(previous)
        return next(
            (
                session
                for session in candidates
                if session.closes_at <= instant <= session.closes_at.plus(tolerance)
            ),
            None,
        )
