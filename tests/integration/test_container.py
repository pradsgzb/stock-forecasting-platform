from datetime import UTC, datetime

import pytest

from stock_predictor.bootstrap.container import build_container
from stock_predictor.bootstrap.settings import PlatformSettings
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.calendar import MarketPhase
from stock_predictor.domain.market.identifiers import MarketIdentifierCode
from stock_predictor.ports.calendar_provider import CalendarProvider
from stock_predictor.ports.instrument_repository import InstrumentRepository

pytestmark = pytest.mark.integration


def test_composition_root_builds_protocol_compatible_dependencies() -> None:
    container = build_container(PlatformSettings(_env_file=None))

    assert isinstance(container.calendars, CalendarProvider)
    assert isinstance(container.instruments, InstrumentRepository)
    assert container.settings.app.name == "stock-forecasting-platform"


def test_market_phase_uses_exchange_calendar() -> None:
    container = build_container(PlatformSettings(_env_file=None))
    mic = MarketIdentifierCode("XNYS")

    assert container.market_time_service.phase(
        mic, UtcInstant(datetime(2025, 7, 3, 12, 0, tzinfo=UTC))
    ) is MarketPhase.PRE_OPEN
    assert container.market_time_service.phase(
        mic, UtcInstant(datetime(2025, 7, 3, 15, 0, tzinfo=UTC))
    ) is MarketPhase.OPEN
    assert container.market_time_service.phase(
        mic, UtcInstant(datetime(2025, 7, 3, 18, 0, tzinfo=UTC))
    ) is MarketPhase.POST_CLOSE
