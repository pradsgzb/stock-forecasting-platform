from datetime import UTC, date, datetime

from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.market.calendar import MarketPhase, TradingBreak, TradingSession
from stock_predictor.domain.market.identifiers import MarketIdentifierCode


def _instant(hour: int, minute: int = 0) -> UtcInstant:
    return UtcInstant(datetime(2026, 1, 2, hour, minute, tzinfo=UTC))


def test_session_phase_and_break_behavior() -> None:
    session = TradingSession(
        exchange_mic=MarketIdentifierCode("TEST"),
        session_date=date(2026, 1, 2),
        opens_at=_instant(9),
        closes_at=_instant(16),
        breaks=(TradingBreak(InstantInterval(_instant(12), _instant(13))),),
    )

    assert session.phase_at(_instant(8, 59)) is MarketPhase.PRE_OPEN
    assert session.phase_at(_instant(10)) is MarketPhase.OPEN
    assert session.phase_at(_instant(12, 30)) is MarketPhase.BREAK
    assert session.phase_at(_instant(16)) is MarketPhase.POST_CLOSE
    assert session.is_open_at(_instant(13))
    assert not session.is_open_at(_instant(12))
