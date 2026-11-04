from datetime import date
from types import MappingProxyType

import pytest

from stock_predictor.domain.common.errors import DomainValidationError, ProviderContractError
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market_data.contracts import (
    BarFrequency,
    MarketDataKind,
    MarketDataPage,
    PriceAdjustment,
    PriceBarRequest,
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderPriceBar,
    RecordOperation,
)


def _capabilities(provider=ProviderName("synthetic")) -> ProviderCapabilities:
    return ProviderCapabilities(
        ProviderDescriptor(provider, "1.2.3", "Test Provider"),
        frozenset({MarketDataKind.PRICE_BARS}),
        frozenset({MarketIdentifierCode("XNYS")}),
        frozenset({BarFrequency.DAILY}),
        frozenset({PriceAdjustment.RAW}),
        max_symbols_per_request=2,
        max_days_per_request=10,
    )


def test_request_is_normalized_and_fingerprint_is_order_independent(
    synthetic_provider_name, xnys
) -> None:
    left = PriceBarRequest(
        synthetic_provider_name,
        xnys,
        (TickerSymbol("ZZZ"), TickerSymbol("AAA")),
        date(2025, 1, 1),
        date(2025, 1, 2),
    )
    right = PriceBarRequest(
        synthetic_provider_name,
        xnys,
        (TickerSymbol("AAA"), TickerSymbol("ZZZ")),
        date(2025, 1, 1),
        date(2025, 1, 2),
    )

    assert left.symbols == (TickerSymbol("AAA"), TickerSymbol("ZZZ"))
    assert left.request_fingerprint == right.request_fingerprint


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"symbols": ()}, "at least one"),
        ({"symbols": (TickerSymbol("AAA"), TickerSymbol("AAA"))}, "unique"),
        ({"start": date(2025, 1, 3), "end": date(2025, 1, 2)}, "end"),
        ({"page_size": 0}, "page_size"),
    ],
)
def test_request_rejects_invalid_shapes(synthetic_provider_name, xnys, kwargs, match) -> None:
    values = {
        "provider": synthetic_provider_name,
        "exchange_mic": xnys,
        "symbols": (TickerSymbol("AAA"),),
        "start": date(2025, 1, 1),
        "end": date(2025, 1, 2),
    }
    values.update(kwargs)
    with pytest.raises(DomainValidationError, match=match):
        PriceBarRequest(**values)


def test_capabilities_validate_supported_request(synthetic_provider_name, xnys) -> None:
    request = PriceBarRequest(
        synthetic_provider_name,
        xnys,
        (TickerSymbol("AAA"),),
        date(2025, 1, 1),
        date(2025, 1, 2),
    )
    _capabilities().validate(request)


@pytest.mark.parametrize(
    "price_request,match",
    [
        (
            PriceBarRequest(
                ProviderName("other"),
                MarketIdentifierCode("XNYS"),
                (TickerSymbol("AAA"),),
                date(2025, 1, 1),
                date(2025, 1, 2),
            ),
            "does not match",
        ),
        (
            PriceBarRequest(
                ProviderName("synthetic"),
                MarketIdentifierCode("XBOM"),
                (TickerSymbol("AAA"),),
                date(2025, 1, 1),
                date(2025, 1, 2),
            ),
            "exchange",
        ),
        (
            PriceBarRequest(
                ProviderName("synthetic"),
                MarketIdentifierCode("XNYS"),
                (TickerSymbol("AAA"), TickerSymbol("BBB"), TickerSymbol("CCC")),
                date(2025, 1, 1),
                date(2025, 1, 2),
            ),
            "symbol limit",
        ),
        (
            PriceBarRequest(
                ProviderName("synthetic"),
                MarketIdentifierCode("XNYS"),
                (TickerSymbol("AAA"),),
                date(2025, 1, 1),
                date(2025, 2, 1),
            ),
            "date-range",
        ),
    ],
)
def test_capabilities_reject_unsupported_requests(price_request, match) -> None:
    with pytest.raises(ProviderContractError, match=match):
        _capabilities().validate(price_request)


def test_capabilities_require_nonempty_contract() -> None:
    with pytest.raises(DomainValidationError, match="require"):
        ProviderCapabilities(
            ProviderDescriptor(ProviderName("test"), "1", "Test"),
            frozenset(),
            frozenset(),
            frozenset(),
            frozenset(),
            1,
            1,
        )


def test_provider_record_supports_upsert_and_immutable_metadata(make_provider_bar) -> None:
    record = make_provider_bar()

    assert record.close_price is not None
    assert record.natural_key[-1] is BarFrequency.DAILY
    assert isinstance(record.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        record.metadata["new"] = "value"


def test_provider_record_operation_contracts(make_provider_bar) -> None:
    with pytest.raises(DomainValidationError, match="require OHLC"):
        ProviderPriceBar(
            provider_record_id="bad",
            provider=ProviderName("synthetic"),
            symbol=TickerSymbol("AAA"),
            exchange_mic=MarketIdentifierCode("XNYS"),
            session_date=date(2025, 1, 2),
            frequency=BarFrequency.DAILY,
            operation=RecordOperation.UPSERT,
            revision=0,
            currency=make_provider_bar().currency,
            timeline=make_provider_bar().timeline,
        )
    template = make_provider_bar()
    with pytest.raises(DomainValidationError, match="must not carry"):
        ProviderPriceBar(
            provider_record_id="delete-with-values",
            provider=template.provider,
            symbol=template.symbol,
            exchange_mic=template.exchange_mic,
            session_date=template.session_date,
            frequency=template.frequency,
            operation=RecordOperation.DELETE,
            revision=1,
            currency=template.currency,
            timeline=template.timeline,
            open_price="1",
        )
    with pytest.raises(DomainValidationError, match="revision"):
        make_provider_bar(revision=-1)


def test_market_data_page_validates_and_hashes(fixed_instant, synthetic_provider_name) -> None:
    page = MarketDataPage(
        provider=synthetic_provider_name,
        request_fingerprint="a" * 64,
        provider_request_id="request-1",
        retrieved_at=fixed_instant,
        schema_version="v1",
        content_type="Application/JSON",
        raw_payload=b"{}",
        next_cursor=None,
        advertised_record_count=0,
        response_metadata={"x": "y"},
    )

    assert page.content_type == "application/json"
    assert len(page.payload_digest) == 64
    with pytest.raises(DomainValidationError, match="payload"):
        MarketDataPage(
            synthetic_provider_name,
            "a" * 64,
            "id",
            fixed_instant,
            "v1",
            "application/json",
            b"",
            None,
            0,
        )


def test_market_data_page_rejects_non_hexadecimal_fingerprint(
    fixed_instant, synthetic_provider_name
) -> None:
    with pytest.raises(DomainValidationError, match="SHA-256"):
        MarketDataPage(
            provider=synthetic_provider_name,
            request_fingerprint="z" * 64,
            provider_request_id="request-1",
            retrieved_at=fixed_instant,
            schema_version="v1",
            content_type="application/json",
            raw_payload=b"{}",
            next_cursor=None,
            advertised_record_count=0,
        )
