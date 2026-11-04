from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.application.quality.models import DecodedPriceBar
from stock_predictor.application.quality.rules import (
    DuplicateRecordRule,
    MonotonicOrderingRule,
    PriceAndVolumeRule,
    RequestConformanceRule,
    TimelinessRule,
    TradingSessionRule,
    ValidationContext,
)
from stock_predictor.domain.common.temporal import InformationTimeline, UtcInstant
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market_data.contracts import PriceBarRequest
from stock_predictor.domain.market_data.ingestion import Sha256Digest


def _decoded(record, index: int = 0) -> DecodedPriceBar:
    return DecodedPriceBar(record, 1, index, Sha256Digest("a" * 64))


def _context(provider, xnys, sample_symbol, exchange_catalog) -> ValidationContext:
    return ValidationContext(
        PriceBarRequest(
            provider,
            xnys,
            (sample_symbol,),
            date(2025, 7, 1),
            date(2025, 7, 3),
        ),
        ExchangeCalendarsProvider(exchange_catalog),
        timedelta(hours=6),
    )


def test_request_conformance_reports_every_contract_mismatch(
    make_provider_bar,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    exchange_catalog,
) -> None:
    record = make_provider_bar(date(2025, 7, 4))
    record = replace(
        record,
        provider=ProviderName("other"),
        exchange_mic=MarketIdentifierCode("XBOM"),
        symbol=TickerSymbol("OTHER"),
    )
    findings = RequestConformanceRule().evaluate(
        (_decoded(record),),
        _context(synthetic_provider_name, xnys, sample_symbol, exchange_catalog),
    )

    assert {item.message for item in findings} == {
        "Provider does not match request",
        "Exchange does not match request",
        "Symbol was not requested",
        "Session date is outside request range",
    }
    assert all(item.record_index == 0 for item in findings)


def test_request_conformance_passes_matching_record(
    make_provider_bar,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    exchange_catalog,
) -> None:
    findings = RequestConformanceRule().evaluate(
        (_decoded(make_provider_bar(date(2025, 7, 2))),),
        _context(synthetic_provider_name, xnys, sample_symbol, exchange_catalog),
    )
    assert findings == ()


def test_price_and_volume_rule_reports_price_volume_and_ohlc_failures(
    make_provider_bar,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    exchange_catalog,
) -> None:
    context = _context(synthetic_provider_name, xnys, sample_symbol, exchange_catalog)
    non_positive = make_provider_bar(open_price="-1")
    negative_volume = make_provider_bar(volume="-1", provider_record_id="negative-volume")
    inconsistent = make_provider_bar(
        open_price="100",
        high_price="101",
        low_price="99",
        close_price="105",
        provider_record_id="inconsistent",
    )

    findings = PriceAndVolumeRule().evaluate(
        tuple(
            _decoded(item, index)
            for index, item in enumerate(
                (non_positive, negative_volume, inconsistent)
            )
        ),
        context,
    )

    assert [item.message for item in findings] == [
        "OHLC prices must be positive",
        "Volume cannot be negative",
        "OHLC relationship is inconsistent",
    ]


def test_price_rule_skips_tombstones(
    make_provider_bar,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    exchange_catalog,
) -> None:
    from stock_predictor.domain.market_data.contracts import RecordOperation

    findings = PriceAndVolumeRule().evaluate(
        (_decoded(make_provider_bar(operation=RecordOperation.DELETE)),),
        _context(synthetic_provider_name, xnys, sample_symbol, exchange_catalog),
    )
    assert findings == ()


def test_duplicate_rule_detects_record_ids_and_natural_revisions(
    make_provider_bar,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    exchange_catalog,
) -> None:
    first = make_provider_bar(provider_record_id="duplicate")
    second = make_provider_bar(provider_record_id="duplicate")
    findings = DuplicateRecordRule().evaluate(
        (_decoded(first, 0), _decoded(second, 1)),
        _context(synthetic_provider_name, xnys, sample_symbol, exchange_catalog),
    )

    assert [item.message for item in findings] == [
        "Duplicate provider record ID",
        "Duplicate natural key and revision",
    ]


def test_trading_session_rule_reports_holiday_and_out_of_session_event(
    make_provider_bar,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    exchange_catalog,
) -> None:
    holiday = make_provider_bar(date(2025, 7, 4))
    event = UtcInstant(datetime(2025, 7, 2, 22, 0, tzinfo=UTC))
    outside = replace(
        make_provider_bar(date(2025, 7, 2), provider_record_id="outside"),
        timeline=InformationTimeline(
            event,
            event.plus(timedelta(minutes=1)),
            event.plus(timedelta(minutes=2)),
            event.plus(timedelta(minutes=3)),
        ),
    )
    findings = TradingSessionRule().evaluate(
        (_decoded(holiday, 0), _decoded(outside, 1)),
        _context(synthetic_provider_name, xnys, sample_symbol, exchange_catalog),
    )

    assert [item.message for item in findings] == [
        "Bar date is not a trading session",
        "Bar event time is outside the regular session",
    ]
    assert findings[1].observed is not None
    assert findings[1].expected is not None


def test_timeliness_and_ordering_rules_cover_warning_and_pass_paths(
    make_provider_bar,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    exchange_catalog,
) -> None:
    context = _context(synthetic_provider_name, xnys, sample_symbol, exchange_catalog)
    slow = make_provider_bar(processed_delay_minutes=400)
    timely = make_provider_bar(date(2025, 7, 1), provider_record_id="earlier")

    assert len(TimelinessRule().evaluate((_decoded(slow),), context)) == 1
    assert TimelinessRule().evaluate((_decoded(timely),), context) == ()
    assert MonotonicOrderingRule().evaluate(
        (_decoded(slow), _decoded(timely, 1)), context
    )[0].message == "Decoded records are not in deterministic order"
    assert MonotonicOrderingRule().evaluate(
        (_decoded(timely), _decoded(slow, 1)), context
    ) == ()
