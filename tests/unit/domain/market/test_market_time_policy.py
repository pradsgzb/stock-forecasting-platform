from datetime import UTC, date, datetime, timedelta

from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.calendar import TradingSession
from stock_predictor.domain.market.identifiers import MarketIdentifierCode
from stock_predictor.domain.market.market_time import MarketDecisionPolicy


def test_decision_policy_applies_validation_delay() -> None:
    session = TradingSession(
        MarketIdentifierCode("TEST"),
        date(2026, 1, 2),
        UtcInstant(datetime(2026, 1, 2, 9, tzinfo=UTC)),
        UtcInstant(datetime(2026, 1, 2, 16, tzinfo=UTC)),
    )
    policy = MarketDecisionPolicy(timedelta(minutes=20), timedelta(minutes=10))

    assert policy.data_cutoff(session).value == datetime(2026, 1, 2, 16, 20, tzinfo=UTC)
    assert policy.earliest_decision_time(session).value == datetime(
        2026, 1, 2, 16, 30, tzinfo=UTC
    )
