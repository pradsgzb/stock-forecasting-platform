from datetime import date

import pytest

from stock_predictor.adapters.market_data.synthetic_provider import SyntheticMarketDataProvider
from stock_predictor.domain.common.errors import ProviderContractError
from stock_predictor.domain.market.identifiers import TickerSymbol
from stock_predictor.domain.market_data.contracts import MarketDataPage, PriceBarRequest
from stock_predictor.ports.market_data_provider import PermanentMarketDataProviderError


def test_synthetic_provider_pages_and_round_trips(
    make_provider_bar, fixed_instant, synthetic_provider_name, xnys, sample_symbol
) -> None:
    records = (
        make_provider_bar(date(2025, 7, 1), close_price="101"),
        make_provider_bar(date(2025, 7, 2), close_price="102"),
        make_provider_bar(date(2025, 7, 3), close_price="103"),
    )
    from stock_predictor.domain.common.clock import FixedClock

    provider = SyntheticMarketDataProvider(records, FixedClock(fixed_instant))
    request = PriceBarRequest(
        synthetic_provider_name,
        xnys,
        (sample_symbol,),
        date(2025, 7, 1),
        date(2025, 7, 3),
        page_size=2,
    )

    first = provider.fetch_price_bars(request)
    second = provider.fetch_price_bars(request, cursor=first.next_cursor)

    assert first.next_cursor == "2"
    assert second.next_cursor is None
    assert [item.close_price for item in provider.decode_price_bars(first)] == [101, 102]
    assert [item.close_price for item in provider.decode_price_bars(second)] == [103]


def test_synthetic_provider_rejects_invalid_cursor(
    make_provider_bar, fixed_instant, synthetic_provider_name, xnys, sample_symbol
) -> None:
    from stock_predictor.domain.common.clock import FixedClock

    provider = SyntheticMarketDataProvider((make_provider_bar(),), FixedClock(fixed_instant))
    request = PriceBarRequest(
        synthetic_provider_name,
        xnys,
        (sample_symbol,),
        date(2025, 7, 1),
        date(2025, 7, 3),
    )
    with pytest.raises(PermanentMarketDataProviderError):
        provider.fetch_price_bars(request, cursor="not-an-integer")


def test_synthetic_provider_rejects_malformed_payload(
    fixed_instant, synthetic_provider_name
) -> None:
    from stock_predictor.domain.common.clock import FixedClock

    provider = SyntheticMarketDataProvider((), FixedClock(fixed_instant))
    page = MarketDataPage(
        synthetic_provider_name,
        "a" * 64,
        "id",
        fixed_instant,
        provider.SCHEMA_VERSION,
        provider.CONTENT_TYPE,
        b"not json",
        None,
        None,
    )
    with pytest.raises(ProviderContractError, match="valid JSON"):
        provider.decode_price_bars(page)
