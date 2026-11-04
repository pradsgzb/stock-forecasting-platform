from datetime import UTC, date, datetime, timedelta

import pytest

from stock_predictor.application.market_time.service import MarketTimeService
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.calendar import MarketPhase, TradingSession
from stock_predictor.domain.market.exchange import Exchange, ExchangeCatalog
from stock_predictor.domain.market.identifiers import CountryCode, MarketIdentifierCode


class StubCalendar:
    def __init__(self, session: TradingSession | None) -> None:
        self.session_value = session

    def is_session(self, mic, session_date):
        return self.session_value is not None and self.session_value.session_date == session_date

    def session(self, mic, session_date):
        assert self.session_value is not None
        return self.session_value

    def session_or_none(self, mic, session_date):
        if self.session_value is not None and self.session_value.session_date == session_date:
            return self.session_value
        return None

    def sessions(self, mic, start, end):
        return () if self.session_value is None else (self.session_value,)

    def next_session(self, mic, after):
        assert self.session_value is not None
        return self.session_value

    def previous_session(self, mic, before):
        assert self.session_value is not None
        return self.session_value

    def session_containing(self, mic, instant):
        if (
            self.session_value
            and self.session_value.opens_at <= instant < self.session_value.closes_at
        ):
            return self.session_value
        return None


def _service(session: TradingSession | None) -> MarketTimeService:
    exchange = Exchange(
        MarketIdentifierCode("TEST"),
        "Test",
        CountryCode("US"),
        "UTC",
        None,
    )
    return MarketTimeService(StubCalendar(session), ExchangeCatalog((exchange,)))


def _session() -> TradingSession:
    return TradingSession(
        MarketIdentifierCode("TEST"),
        date(2026, 1, 2),
        UtcInstant(datetime(2026, 1, 2, 9, tzinfo=UTC)),
        UtcInstant(datetime(2026, 1, 2, 16, tzinfo=UTC)),
    )


def test_closed_day_and_next_open() -> None:
    session = _session()
    service = _service(session)
    before = UtcInstant(datetime(2026, 1, 2, 8, tzinfo=UTC))

    assert service.phase(MarketIdentifierCode("TEST"), before) is MarketPhase.PRE_OPEN
    assert service.next_open(MarketIdentifierCode("TEST"), before) == session.opens_at


def test_session_tolerance_and_validation() -> None:
    session = _session()
    service = _service(session)
    just_closed = UtcInstant(datetime(2026, 1, 2, 16, 5, tzinfo=UTC))

    assert service.session_with_tolerance(
        MarketIdentifierCode("TEST"), just_closed, timedelta(minutes=10)
    ) == session
    assert service.session_with_tolerance(
        MarketIdentifierCode("TEST"), just_closed, timedelta(minutes=2)
    ) is None
    with pytest.raises(ValueError, match="negative"):
        service.session_with_tolerance(
            MarketIdentifierCode("TEST"), just_closed, timedelta(minutes=-1)
        )


def test_market_phase_closed_when_no_session() -> None:
    service = _service(None)
    instant = UtcInstant(datetime(2026, 1, 3, 12, tzinfo=UTC))
    assert service.phase(MarketIdentifierCode("TEST"), instant) is MarketPhase.CLOSED


def test_session_tolerance_can_cross_exchange_local_midnight() -> None:
    session = _session()
    service = _service(session)
    after_midnight = UtcInstant(datetime(2026, 1, 3, 0, 30, tzinfo=UTC))

    assert service.session_with_tolerance(
        MarketIdentifierCode("TEST"), after_midnight, timedelta(hours=9)
    ) == session
