from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.adapters.repositories.in_memory_price_bar_repository import (
    InMemoryAdjustmentFactorRepository,
    InMemoryPriceBarRepository,
)
from stock_predictor.application.point_in_time.service import PointInTimePriceService
from stock_predictor.domain.common.errors import (
    DomainValidationError,
    PointInTimeViolationError,
)
from stock_predictor.domain.common.identifiers import AdjustmentFactorId, PriceBarId
from stock_predictor.domain.common.money import Price
from stock_predictor.domain.common.temporal import InformationTimeline, UtcInstant
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.market.identifiers import ProviderName
from stock_predictor.domain.market_data.contracts import BarFrequency, RecordOperation
from stock_predictor.domain.market_data.ingestion import Sha256Digest
from stock_predictor.domain.market_data.point_in_time import (
    AdjustmentFactor,
    NormalizedPriceBar,
    PriceBarKey,
    PriceBarValues,
)


def _instant(day: int, hour: int = 12) -> UtcInstant:
    return UtcInstant(datetime(2026, 1, day, hour, tzinfo=UTC))


def _timeline(session_date: date, processed: UtcInstant) -> InformationTimeline:
    event = UtcInstant(
        datetime(session_date.year, session_date.month, session_date.day, 20, tzinfo=UTC)
    )
    published = event.plus(timedelta(minutes=1))
    received = published.plus(timedelta(minutes=1))
    return InformationTimeline(event, published, received, processed)


def _bar(
    instrument,
    xnys,
    session_date: date,
    normalized_at: UtcInstant,
    *,
    revision: int = 0,
    close: str = "100",
    operation: RecordOperation = RecordOperation.UPSERT,
    supersedes=None,
) -> NormalizedPriceBar:
    values = None
    if operation is RecordOperation.UPSERT:
        values = PriceBarValues(
            Price("99", instrument.trading_currency),
            Price("105", instrument.trading_currency),
            Price("98", instrument.trading_currency),
            Price(close, instrument.trading_currency),
            Quantity("1000"),
        )
    return NormalizedPriceBar(
        PriceBarId.new(),
        PriceBarKey(instrument.instrument_id, xnys, session_date, BarFrequency.DAILY),
        ProviderName("synthetic"),
        f"{session_date}-r{revision}",
        revision,
        operation,
        values,
        _timeline(session_date, normalized_at),
        normalized_at,
        Sha256Digest("a" * 64),
        1,
        revision,
        supersedes,
    )


def _service(mapped_instrument_repository, exchange_catalog):
    instruments, instrument = mapped_instrument_repository
    bars = InMemoryPriceBarRepository()
    adjustments = InMemoryAdjustmentFactorRepository()
    service = PointInTimePriceService(
        bars,
        adjustments,
        instruments,
        ExchangeCalendarsProvider(exchange_catalog),
    )
    return service, bars, adjustments, instrument


def test_raw_history_resolves_corrections_and_tombstones_by_cutoff(
    mapped_instrument_repository, exchange_catalog, xnys
) -> None:
    service, bars, _, instrument = _service(
        mapped_instrument_repository, exchange_catalog
    )
    original = _bar(instrument, xnys, date(2025, 7, 2), _instant(2), close="100")
    correction = _bar(
        instrument,
        xnys,
        date(2025, 7, 2),
        _instant(3),
        revision=1,
        close="102",
        supersedes=original.bar_id,
    )
    tombstone = _bar(
        instrument,
        xnys,
        date(2025, 7, 2),
        _instant(4),
        revision=2,
        operation=RecordOperation.DELETE,
        supersedes=correction.bar_id,
    )
    for item in (original, correction, tombstone):
        bars.append(item)

    assert service.raw_history(
        instrument.instrument_id, date(2025, 7, 2), date(2025, 7, 2), _instant(2, 13)
    ) == (original,)
    assert service.raw_history(
        instrument.instrument_id, date(2025, 7, 2), date(2025, 7, 2), _instant(3, 13)
    ) == (correction,)
    assert service.raw_history(
        instrument.instrument_id, date(2025, 7, 2), date(2025, 7, 2), _instant(4, 13)
    ) == ()


def test_feature_history_applies_only_adjustments_known_at_cutoff(
    mapped_instrument_repository, exchange_catalog, xnys
) -> None:
    service, bars, adjustments, instrument = _service(
        mapped_instrument_repository, exchange_catalog
    )
    for index, (session_date, close) in enumerate(
        ((date(2025, 7, 1), "100"), (date(2025, 7, 2), "102"), (date(2025, 7, 3), "104"))
    ):
        bars.append(_bar(instrument, xnys, session_date, _instant(2), close=close))
    timeline = _timeline(date(2025, 7, 3), _instant(3))
    factor = AdjustmentFactor(
        AdjustmentFactorId.new(),
        instrument.instrument_id,
        date(2025, 7, 3),
        "0.5",
        "2",
        0,
        timeline,
        ProviderName("synthetic"),
        Sha256Digest("b" * 64),
    )
    adjustments.append(factor)

    before_factor = service.feature_history(
        instrument.instrument_id, date(2025, 7, 3), _instant(2, 13), 3
    )
    after_factor = service.feature_history(
        instrument.instrument_id, date(2025, 7, 3), _instant(3, 13), 3
    )
    raw = service.feature_history(
        instrument.instrument_id,
        date(2025, 7, 3),
        _instant(3, 13),
        3,
        adjusted=False,
    )

    assert [item.close_price for item in before_factor] == [
        Decimal("100"),
        Decimal("102"),
        Decimal("104"),
    ]
    assert [item.close_price for item in after_factor] == [
        Decimal("50.0"),
        Decimal("51.0"),
        Decimal("104"),
    ]
    assert [item.volume for item in after_factor] == [
        Decimal("2000"),
        Decimal("2000"),
        Decimal("1000"),
    ]
    assert [item.close_price for item in raw] == [
        Decimal("100"),
        Decimal("102"),
        Decimal("104"),
    ]
    assert after_factor[0].source_fingerprint != raw[0].source_fingerprint


def test_feature_history_uses_previous_session_for_non_trading_as_of(
    mapped_instrument_repository, exchange_catalog, xnys
) -> None:
    service, bars, _, instrument = _service(
        mapped_instrument_repository, exchange_catalog
    )
    bars.append(_bar(instrument, xnys, date(2025, 7, 3), _instant(2), close="104"))

    history = service.feature_history(
        instrument.instrument_id,
        date(2025, 7, 5),
        _instant(3),
        1,
    )

    assert [item.session_date for item in history] == [date(2025, 7, 3)]
    assert len(service.input_fingerprint(history)) == 64
    assert service.input_fingerprint(history) == service.input_fingerprint(history)


def test_point_in_time_service_validates_history_size_and_repository_contract(
    mapped_instrument_repository, exchange_catalog, xnys
) -> None:
    service, _, _, instrument = _service(mapped_instrument_repository, exchange_catalog)
    with pytest.raises(DomainValidationError, match="positive"):
        service.feature_history(instrument.instrument_id, date(2025, 7, 2), _instant(3), 0)

    unavailable = _bar(instrument, xnys, date(2025, 7, 2), _instant(4))

    class BrokenRepository:
        def query_as_known_at(self, *args, **kwargs):
            return (unavailable,)

    broken = PointInTimePriceService(
        BrokenRepository(),
        InMemoryAdjustmentFactorRepository(),
        mapped_instrument_repository[0],
        ExchangeCalendarsProvider(exchange_catalog),
    )
    with pytest.raises(PointInTimeViolationError, match="unavailable"):
        broken.raw_history(
            instrument.instrument_id,
            date(2025, 7, 2),
            date(2025, 7, 2),
            _instant(3),
        )
