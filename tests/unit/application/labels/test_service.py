from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
    InMemoryInstrumentRepository,
)
from stock_predictor.application.labels.service import TargetLabelService
from stock_predictor.domain.common.errors import LabelComputationError
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    PriceBarId,
    TargetDefinitionId,
)
from stock_predictor.domain.common.temporal import (
    HorizonUnit,
    PredictionHorizon,
    UtcInstant,
)
from stock_predictor.domain.market.instrument import Instrument
from stock_predictor.domain.market_data.features import FeatureInputBar
from stock_predictor.domain.modeling.targets import TargetDefinition, TargetKind


class FakePrices:
    def __init__(self, paths):
        self.paths = paths
        self.calls = []

    def price_path(self, instrument_id, start, end, cutoff, **kwargs):
        self.calls.append((instrument_id, start, end, cutoff, kwargs))
        return self.paths.get(instrument_id, ())


def bar(session_date, close, *, low=None, high=None, hour=21):
    close_value = Decimal(str(close))
    return FeatureInputBar(
        bar_id=PriceBarId.new(),
        session_date=session_date,
        open_price=close_value,
        high_price=Decimal(str(high if high is not None else close_value)),
        low_price=Decimal(str(low if low is not None else close_value)),
        close_price=close_value,
        volume=Decimal("1000"),
        available_at=UtcInstant(
            datetime(
                session_date.year,
                session_date.month,
                session_date.day,
                hour,
                tzinfo=UTC,
            )
        ),
        source_fingerprint="a" * 64,
    )


def target(kind, *, horizon=2, benchmark=None):
    return TargetDefinition(
        TargetDefinitionId.new(),
        kind.value,
        "1.0.0",
        kind,
        PredictionHorizon(horizon, HorizonUnit.TRADING_SESSIONS),
        benchmark_instrument_id=benchmark,
    )


def build_service(sample_instrument, exchange_catalog, usd):
    benchmark = Instrument(
        instrument_id=InstrumentId.new(),
        display_name="Benchmark",
        asset_class=sample_instrument.asset_class,
        primary_exchange_mic=sample_instrument.primary_exchange_mic,
        trading_currency=usd,
        listing_date=sample_instrument.listing_date,
    )
    repository = InMemoryInstrumentRepository()
    repository.add(sample_instrument)
    repository.add(benchmark)
    dates = (date(2025, 7, 2), date(2025, 7, 3), date(2025, 7, 7))
    prices = FakePrices(
        {
            sample_instrument.instrument_id: (
                bar(dates[0], 100, low=99, high=101),
                bar(dates[1], 105, low=98, high=108),
                bar(dates[2], 110, low=100, high=115),
            ),
            benchmark.instrument_id: (
                bar(dates[0], 200),
                bar(dates[1], 202),
                bar(dates[2], 204),
            ),
        }
    )
    service = TargetLabelService(
        prices,
        repository,
        ExchangeCalendarsProvider(exchange_catalog),
    )
    return service, prices, benchmark, dates


@pytest.mark.parametrize(
    "kind, expected",
    [
        (TargetKind.SIMPLE_RETURN, Decimal("0.1")),
        (TargetKind.DIRECTION, 1),
        (TargetKind.MAX_ADVERSE_EXCURSION, Decimal("-0.02")),
        (TargetKind.MAX_FAVORABLE_EXCURSION, Decimal("0.15")),
    ],
)
def test_label_service_calculates_core_targets(
    sample_instrument, exchange_catalog, usd, kind, expected
) -> None:
    service, _, _, dates = build_service(sample_instrument, exchange_catalog, usd)
    cutoff = UtcInstant(datetime(2025, 7, 8, 0, tzinfo=UTC))

    result = service.calculate(
        target(kind),
        sample_instrument.instrument_id,
        dates[0],
        cutoff,
    )

    assert result.value == expected
    assert result.horizon_end == dates[-1]
    assert len(result.source_bar_ids) == 3


def test_label_service_calculates_log_volatility_and_relative_return(
    sample_instrument, exchange_catalog, usd
) -> None:
    service, _, benchmark, dates = build_service(sample_instrument, exchange_catalog, usd)
    cutoff = UtcInstant(datetime(2025, 7, 8, 0, tzinfo=UTC))

    log_result = service.calculate(
        target(TargetKind.LOG_RETURN),
        sample_instrument.instrument_id,
        dates[0],
        cutoff,
    )
    volatility = service.calculate(
        target(TargetKind.REALIZED_VOLATILITY),
        sample_instrument.instrument_id,
        dates[0],
        cutoff,
    )
    relative = service.calculate(
        target(TargetKind.RELATIVE_RETURN, benchmark=benchmark.instrument_id),
        sample_instrument.instrument_id,
        dates[0],
        cutoff,
    )

    assert Decimal(log_result.value).quantize(Decimal("0.000001")) == Decimal("0.095310")
    assert Decimal(volatility.value) > 0
    assert relative.value == Decimal("0.08")
    assert len(relative.source_bar_ids) == 6


def test_label_service_marks_incomplete_paths_missing(
    sample_instrument, exchange_catalog, usd
) -> None:
    service, prices, _, dates = build_service(sample_instrument, exchange_catalog, usd)
    prices.paths[sample_instrument.instrument_id] = prices.paths[
        sample_instrument.instrument_id
    ][:2]

    result = service.calculate(
        target(TargetKind.SIMPLE_RETURN),
        sample_instrument.instrument_id,
        dates[0],
        UtcInstant(datetime(2025, 7, 8, 0, tzinfo=UTC)),
    )

    assert result.is_missing
    assert "expected 3" in result.missing_reason


def test_label_service_enforces_timing_and_rank_api(
    sample_instrument, exchange_catalog, usd
) -> None:
    service, _, _, dates = build_service(sample_instrument, exchange_catalog, usd)
    with pytest.raises(LabelComputationError, match="before the target"):
        service.calculate(
            target(TargetKind.SIMPLE_RETURN),
            sample_instrument.instrument_id,
            dates[0],
            UtcInstant(datetime(2025, 7, 7, 12, tzinfo=UTC)),
        )
    with pytest.raises(LabelComputationError, match="peer group"):
        service.calculate(
            target(TargetKind.CROSS_SECTIONAL_RANK),
            sample_instrument.instrument_id,
            dates[0],
            UtcInstant(datetime(2025, 7, 8, 0, tzinfo=UTC)),
        )
    with pytest.raises(LabelComputationError, match="must be a date"):
        service.calculate(
            target(TargetKind.SIMPLE_RETURN),
            sample_instrument.instrument_id,
            "2025-07-02",
            UtcInstant(datetime(2025, 7, 8, 0, tzinfo=UTC)),
        )


def test_cross_sectional_rank_uses_average_ties_and_preserves_missing(
    sample_instrument, exchange_catalog, usd
) -> None:
    service, _, benchmark, dates = build_service(sample_instrument, exchange_catalog, usd)
    cutoff = UtcInstant(datetime(2025, 7, 8, 0, tzinfo=UTC))
    source_target = target(TargetKind.SIMPLE_RETURN)
    first = service.calculate(
        source_target,
        sample_instrument.instrument_id,
        dates[0],
        cutoff,
    )
    second = service.calculate(
        source_target,
        benchmark.instrument_id,
        dates[0],
        cutoff,
    )
    missing = type(first)(
        label_id=type(first.label_id).new(),
        target=source_target,
        instrument_id=InstrumentId.new(),
        as_of=first.as_of,
        horizon_end=first.horizon_end,
        outcome_cutoff=cutoff,
        available_at=cutoff,
        value=None,
        missing_reason="missing",
        source_bar_ids=(),
    )

    ranked = service.rank_cross_section(
        target(TargetKind.CROSS_SECTIONAL_RANK),
        (first, second, missing),
    )

    assert ranked[0].value == Decimal(1)
    assert ranked[1].value == Decimal(0)
    assert ranked[2].is_missing
    assert all(item.available_at == cutoff for item in ranked)
    assert all(len(item.source_bar_ids) == 6 for item in ranked)
    assert len({item.source_bar_ids for item in ranked}) == 1

    with pytest.raises(LabelComputationError, match="Rank target"):
        service.rank_cross_section(source_target, (first, second))


def test_cross_sectional_rank_rejects_mixed_cutoffs_and_targets(
    sample_instrument, exchange_catalog, usd
) -> None:
    service, _, benchmark, dates = build_service(sample_instrument, exchange_catalog, usd)
    cutoff = UtcInstant(datetime(2025, 7, 8, 0, tzinfo=UTC))
    source_target = target(TargetKind.SIMPLE_RETURN)
    first = service.calculate(
        source_target,
        sample_instrument.instrument_id,
        dates[0],
        cutoff,
    )
    second = service.calculate(
        source_target,
        benchmark.instrument_id,
        dates[0],
        cutoff,
    )
    rank_target = target(TargetKind.CROSS_SECTIONAL_RANK)

    with pytest.raises(LabelComputationError, match="outcome cutoff"):
        service.rank_cross_section(
            rank_target,
            (first, type(second)(
                second.label_id,
                second.target,
                second.instrument_id,
                second.as_of,
                second.horizon_end,
                cutoff.plus(timedelta(seconds=1)),
                second.available_at,
                second.value,
                second.missing_reason,
                second.source_bar_ids,
            )),
        )

    other_target = target(TargetKind.SIMPLE_RETURN)
    with pytest.raises(LabelComputationError, match="source target"):
        service.rank_cross_section(
            rank_target,
            (first, type(second)(
                second.label_id,
                other_target,
                second.instrument_id,
                second.as_of,
                second.horizon_end,
                second.outcome_cutoff,
                second.available_at,
                second.value,
                second.missing_reason,
                second.source_bar_ids,
            )),
        )
