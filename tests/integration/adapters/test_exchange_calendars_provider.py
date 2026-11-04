from datetime import UTC, date, datetime

import pytest

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.domain.common.errors import NonTradingDayError, UnsupportedExchangeError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.exchange import Exchange, ExchangeCatalog
from stock_predictor.domain.market.identifiers import CountryCode, MarketIdentifierCode

pytestmark = pytest.mark.integration


def _catalog() -> ExchangeCatalog:
    return ExchangeCatalog(
        (
            Exchange(
                MarketIdentifierCode("XNYS"),
                "New York Stock Exchange",
                CountryCode("US"),
                "America/New_York",
                "XNYS",
            ),
            Exchange(
                MarketIdentifierCode("XBOM"),
                "BSE Limited",
                CountryCode("IN"),
                "Asia/Kolkata",
                "XBOM",
            ),
        )
    )


def test_nyse_holiday_and_early_close() -> None:
    provider = ExchangeCalendarsProvider(_catalog())
    mic = MarketIdentifierCode("XNYS")

    assert provider.is_session(mic, date(2025, 7, 4)) is False
    with pytest.raises(NonTradingDayError):
        provider.session(mic, date(2025, 7, 4))

    early_close = provider.session(mic, date(2025, 7, 3))
    assert early_close.opens_at.value == datetime(2025, 7, 3, 13, 30, tzinfo=UTC)
    assert early_close.closes_at.value == datetime(2025, 7, 3, 17, 0, tzinfo=UTC)
    assert early_close.regular_trading_duration.total_seconds() == 3.5 * 60 * 60


def test_next_session_skips_holiday_and_weekend() -> None:
    provider = ExchangeCalendarsProvider(_catalog())

    next_session = provider.next_session(MarketIdentifierCode("XNYS"), date(2025, 7, 3))

    assert next_session.session_date == date(2025, 7, 7)


def test_bse_session_uses_india_market_hours() -> None:
    provider = ExchangeCalendarsProvider(_catalog())

    session = provider.session(MarketIdentifierCode("XBOM"), date(2025, 7, 4))

    assert session.opens_at.value == datetime(2025, 7, 4, 3, 45, tzinfo=UTC)
    assert session.closes_at.value == datetime(2025, 7, 4, 10, 0, tzinfo=UTC)


def test_session_containing_includes_regular_session_interval() -> None:
    provider = ExchangeCalendarsProvider(_catalog())
    instant = UtcInstant(datetime(2025, 7, 3, 15, 0, tzinfo=UTC))

    session = provider.session_containing(MarketIdentifierCode("XNYS"), instant)

    assert session is not None
    assert session.session_date == date(2025, 7, 3)


def test_unknown_calendar_name_fails_explicitly() -> None:
    catalog = ExchangeCatalog(
        (
            Exchange(
                MarketIdentifierCode("XBAD"),
                "Unsupported Test Venue",
                CountryCode("US"),
                "UTC",
                "DOES_NOT_EXIST",
            ),
        )
    )
    provider = ExchangeCalendarsProvider(catalog)

    with pytest.raises(UnsupportedExchangeError, match="unavailable"):
        provider.is_session(MarketIdentifierCode("XBAD"), date(2025, 1, 2))
