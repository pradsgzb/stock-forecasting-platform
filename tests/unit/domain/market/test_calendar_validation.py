from datetime import UTC, date, datetime

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.market.calendar import TradingBreak, TradingSession
from stock_predictor.domain.market.identifiers import MarketIdentifierCode


def _at(hour: int) -> UtcInstant:
    return UtcInstant(datetime(2026, 1, 2, hour, tzinfo=UTC))


def test_session_rejects_invalid_close() -> None:
    with pytest.raises(DomainValidationError, match="close"):
        TradingSession(MarketIdentifierCode("TEST"), date(2026, 1, 2), _at(10), _at(9))


def test_session_rejects_break_outside_or_overlapping() -> None:
    with pytest.raises(DomainValidationError, match="strictly inside"):
        TradingSession(
            MarketIdentifierCode("TEST"),
            date(2026, 1, 2),
            _at(9),
            _at(16),
            (TradingBreak(InstantInterval(_at(8), _at(10))),),
        )

    with pytest.raises(DomainValidationError, match="cannot overlap"):
        TradingSession(
            MarketIdentifierCode("TEST"),
            date(2026, 1, 2),
            _at(9),
            _at(16),
            (
                TradingBreak(InstantInterval(_at(11), _at(13))),
                TradingBreak(InstantInterval(_at(12), _at(14))),
            ),
        )
