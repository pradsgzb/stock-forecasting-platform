from datetime import date

import pytest

from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
    InMemoryInstrumentRepository,
)
from stock_predictor.domain.common.errors import DomainConflictError, DomainNotFoundError
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.identifiers import ProviderName, TickerSymbol
from stock_predictor.domain.market.symbol import SymbolMapping


def test_add_duplicate_save_unknown_and_list(sample_instrument, xnys) -> None:
    repository = InMemoryInstrumentRepository()
    repository.add(sample_instrument)

    with pytest.raises(DomainConflictError, match="already exists"):
        repository.add(sample_instrument)
    with pytest.raises(DomainNotFoundError, match="Cannot save unknown"):
        repository.save(
            type(sample_instrument)(
                instrument_id=InstrumentId.new(),
                display_name=sample_instrument.display_name,
                asset_class=sample_instrument.asset_class,
                primary_exchange_mic=sample_instrument.primary_exchange_mic,
                trading_currency=sample_instrument.trading_currency,
                listing_date=sample_instrument.listing_date,
            )
        )
    assert repository.list_all() == (sample_instrument,)
    with pytest.raises(DomainNotFoundError):
        repository.get(InstrumentId.new())


def test_find_by_symbol_returns_none_and_match(sample_instrument, xnys) -> None:
    mapping = SymbolMapping(
        ProviderName("vendor"),
        TickerSymbol("ABC"),
        xnys,
        EffectivePeriod(date(2020, 1, 1)),
    )
    repository = InMemoryInstrumentRepository()
    repository.add(sample_instrument.with_symbol_mapping(mapping))

    assert repository.find_by_symbol(
        ProviderName("vendor"), TickerSymbol("NONE"), xnys, date(2026, 1, 1)
    ) is None
    assert repository.find_by_symbol(
        ProviderName("vendor"), TickerSymbol("ABC"), xnys, date(2026, 1, 1)
    ) == sample_instrument.with_symbol_mapping(mapping)
