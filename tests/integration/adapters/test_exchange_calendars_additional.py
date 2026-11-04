from datetime import date

import pytest

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.domain.common.errors import DomainValidationError, UnsupportedExchangeError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.exchange import Exchange, ExchangeCatalog
from stock_predictor.domain.market.identifiers import CountryCode, MarketIdentifierCode

pytestmark = pytest.mark.integration


def _provider() -> ExchangeCalendarsProvider:
    return ExchangeCalendarsProvider(
        ExchangeCatalog(
            (
                Exchange(
                    MarketIdentifierCode("XNYS"),
                    "New York Stock Exchange",
                    CountryCode("US"),
                    "America/New_York",
                    "XNYS",
                ),
            )
        )
    )


def test_session_range_and_previous_session() -> None:
    provider = _provider()
    mic = MarketIdentifierCode("XNYS")

    sessions = provider.sessions(mic, date(2025, 7, 1), date(2025, 7, 7))
    assert [item.session_date for item in sessions] == [
        date(2025, 7, 1),
        date(2025, 7, 2),
        date(2025, 7, 3),
        date(2025, 7, 7),
    ]
    assert provider.previous_session(mic, date(2025, 7, 7)).session_date == date(2025, 7, 3)
    assert provider.next_session(mic, date(2025, 7, 5)).session_date == date(2025, 7, 7)


def test_invalid_session_range_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="end cannot be earlier"):
        _provider().sessions(
            MarketIdentifierCode("XNYS"), date(2025, 7, 2), date(2025, 7, 1)
        )


def test_no_calendar_implementation_is_explicit() -> None:
    catalog = ExchangeCatalog(
        (
            Exchange(
                MarketIdentifierCode("XNSE"),
                "National Stock Exchange of India",
                CountryCode("IN"),
                "Asia/Kolkata",
                None,
            ),
        )
    )
    provider = ExchangeCalendarsProvider(catalog)

    with pytest.raises(UnsupportedExchangeError, match="no configured calendar"):
        provider.is_session(MarketIdentifierCode("XNSE"), date(2025, 1, 2))


def test_session_containing_returns_none_when_market_closed() -> None:
    provider = _provider()
    instant = UtcInstant.parse("2025-07-05T15:00:00Z")

    assert provider.session_containing(MarketIdentifierCode("XNYS"), instant) is None
