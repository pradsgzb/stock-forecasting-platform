from datetime import date

import pytest

from stock_predictor.domain.common.errors import (
    DomainValidationError,
    OverlappingEffectivePeriodError,
)
from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.identifiers import ProviderName, TickerSymbol
from stock_predictor.domain.market.instrument import InstrumentStatus
from stock_predictor.domain.market.symbol import SymbolMapping


def test_delisted_status_requires_delisting_date(sample_instrument) -> None:
    values = {
        field: getattr(sample_instrument, field)
        for field in sample_instrument.__dataclass_fields__
        if field not in {"status", "delisting_date"}
    }
    with pytest.raises(DomainValidationError, match="requires a delisting date"):
        type(sample_instrument)(
            **values,
            status=InstrumentStatus.DELISTED,
            delisting_date=None,
        )


def test_symbol_history_allows_ticker_change_without_overlap(sample_instrument, xnys) -> None:
    provider = ProviderName("example")
    old_mapping = SymbolMapping(
        provider,
        TickerSymbol("OLD"),
        xnys,
        EffectivePeriod(date(2020, 1, 2), date(2024, 1, 1)),
    )
    new_mapping = SymbolMapping(
        provider,
        TickerSymbol("NEW"),
        xnys,
        EffectivePeriod(date(2024, 1, 1)),
    )

    changed = sample_instrument.with_symbol_mapping(old_mapping).with_symbol_mapping(new_mapping)

    assert changed.resolve_symbol(provider, xnys, date(2023, 12, 29)) == TickerSymbol("OLD")
    assert changed.resolve_symbol(provider, xnys, date(2024, 1, 1)) == TickerSymbol("NEW")


def test_symbol_history_rejects_overlapping_symbols(sample_instrument, xnys) -> None:
    provider = ProviderName("example")
    first = SymbolMapping(
        provider,
        TickerSymbol("ONE"),
        xnys,
        EffectivePeriod(date(2020, 1, 2), date(2025, 1, 1)),
    )
    overlapping = SymbolMapping(
        provider,
        TickerSymbol("TWO"),
        xnys,
        EffectivePeriod(date(2024, 1, 1)),
    )

    with pytest.raises(OverlappingEffectivePeriodError):
        sample_instrument.with_symbol_mapping(first).with_symbol_mapping(overlapping)
