"""`exchange_calendars` implementation of the calendar-provider port."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import exchange_calendars as xcals
import pandas as pd
from exchange_calendars.errors import CalendarError, InvalidCalendarName
from exchange_calendars.exchange_calendar import ExchangeCalendar

from stock_predictor.domain.common.errors import (
    DomainValidationError,
    NonTradingDayError,
    UnsupportedExchangeError,
)
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.market.calendar import TradingBreak, TradingSession
from stock_predictor.domain.market.exchange import ExchangeCatalog
from stock_predictor.domain.market.identifiers import MarketIdentifierCode


class ExchangeCalendarsProvider:
    """Converts `exchange_calendars` schedules into framework-free domain sessions."""

    __slots__ = ("_catalog", "_calendars")

    def __init__(self, catalog: ExchangeCatalog) -> None:
        self._catalog = catalog
        self._calendars: dict[MarketIdentifierCode, ExchangeCalendar] = {}

    def _calendar(self, mic: MarketIdentifierCode) -> ExchangeCalendar:
        cached = self._calendars.get(mic)
        if cached is not None:
            return cached

        exchange = self._catalog.get(mic)
        if exchange.calendar_name is None:
            msg = f"Exchange {mic} has no configured calendar implementation"
            raise UnsupportedExchangeError(msg)
        try:
            calendar = xcals.get_calendar(exchange.calendar_name)
        except InvalidCalendarName as exc:
            msg = (
                f"Calendar {exchange.calendar_name!r} configured for {mic} is unavailable"
            )
            raise UnsupportedExchangeError(msg) from exc
        self._calendars[mic] = calendar
        return calendar

    @staticmethod
    def _timestamp(value: date) -> pd.Timestamp:
        return pd.Timestamp(value.isoformat())

    @staticmethod
    def _instant(value: pd.Timestamp) -> UtcInstant:
        python_value = value.to_pydatetime()
        if not isinstance(python_value, datetime):  # Defensive for pandas scalar evolution.
            msg = f"Calendar timestamp is not a datetime: {value!r}"
            raise DomainValidationError(msg)
        return UtcInstant(python_value)

    def _to_session(
        self,
        mic: MarketIdentifierCode,
        calendar: ExchangeCalendar,
        label: pd.Timestamp,
    ) -> TradingSession:
        try:
            opens_at = self._instant(calendar.session_open(label))
            closes_at = self._instant(calendar.session_close(label))
            break_start = calendar.session_break_start(label)
            break_end = calendar.session_break_end(label)
        except CalendarError as exc:
            msg = f"Failed to resolve calendar session {mic}/{label.date()}"
            raise NonTradingDayError(msg) from exc

        breaks: tuple[TradingBreak, ...] = ()
        if not pd.isna(break_start) and not pd.isna(break_end):
            breaks = (
                TradingBreak(
                    InstantInterval(
                        start=self._instant(break_start),
                        end=self._instant(break_end),
                    )
                ),
            )
        return TradingSession(
            exchange_mic=mic,
            session_date=label.date(),
            opens_at=opens_at,
            closes_at=closes_at,
            breaks=breaks,
        )

    def is_session(self, mic: MarketIdentifierCode, session_date: date) -> bool:
        calendar = self._calendar(mic)
        try:
            return bool(calendar.is_session(self._timestamp(session_date)))
        except CalendarError as exc:
            msg = f"Calendar date is outside supported bounds: {mic}/{session_date}"
            raise DomainValidationError(msg) from exc

    def session_or_none(
        self,
        mic: MarketIdentifierCode,
        session_date: date,
    ) -> TradingSession | None:
        calendar = self._calendar(mic)
        label = self._timestamp(session_date)
        try:
            if not calendar.is_session(label):
                return None
            canonical_label = calendar.date_to_session(label, direction="none")
        except CalendarError as exc:
            msg = f"Calendar date is outside supported bounds: {mic}/{session_date}"
            raise DomainValidationError(msg) from exc
        return self._to_session(mic, calendar, canonical_label)

    def session(self, mic: MarketIdentifierCode, session_date: date) -> TradingSession:
        session = self.session_or_none(mic, session_date)
        if session is None:
            msg = f"{session_date} is not a trading session for {mic}"
            raise NonTradingDayError(msg)
        return session

    def sessions(
        self,
        mic: MarketIdentifierCode,
        start: date,
        end: date,
    ) -> tuple[TradingSession, ...]:
        if end < start:
            msg = "Session range end cannot be earlier than start"
            raise DomainValidationError(msg)
        calendar = self._calendar(mic)
        try:
            labels = calendar.sessions_in_range(self._timestamp(start), self._timestamp(end))
        except CalendarError as exc:
            msg = f"Calendar range is outside supported bounds: {mic}/{start}..{end}"
            raise DomainValidationError(msg) from exc
        return tuple(self._to_session(mic, calendar, label) for label in labels)

    def next_session(self, mic: MarketIdentifierCode, after: date) -> TradingSession:
        calendar = self._calendar(mic)
        date_value = self._timestamp(after)
        try:
            label = calendar.date_to_session(date_value, direction="next")
            if label.date() == after:
                label = calendar.next_session(label)
        except CalendarError as exc:
            msg = f"No next session available for {mic} after {after}"
            raise NonTradingDayError(msg) from exc
        return self._to_session(mic, calendar, label)

    def previous_session(self, mic: MarketIdentifierCode, before: date) -> TradingSession:
        calendar = self._calendar(mic)
        date_value = self._timestamp(before)
        try:
            label = calendar.date_to_session(date_value, direction="previous")
            if label.date() == before:
                label = calendar.previous_session(label)
        except CalendarError as exc:
            msg = f"No previous session available for {mic} before {before}"
            raise NonTradingDayError(msg) from exc
        return self._to_session(mic, calendar, label)

    def session_containing(
        self,
        mic: MarketIdentifierCode,
        instant: UtcInstant,
    ) -> TradingSession | None:
        exchange = self._catalog.get(mic)
        local_date = instant.value.astimezone(exchange.timezone).date()
        # Adjacent dates cover overnight sessions without assuming that the label date equals
        # the UTC date or even the local date of every instant in the session.
        adjacent_dates = (
            local_date - timedelta(days=1),
            local_date,
            local_date + timedelta(days=1),
        )
        for candidate in adjacent_dates:
            session = self.session_or_none(mic, candidate)
            if session is not None and session.opens_at <= instant < session.closes_at:
                return session
        return None
