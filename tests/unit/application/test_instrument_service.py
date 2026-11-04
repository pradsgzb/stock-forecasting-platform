from datetime import date

import pytest

from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
    InMemoryInstrumentRepository,
)
from stock_predictor.application.instruments.commands import AddSymbolMapping, RegisterInstrument
from stock_predictor.application.instruments.queries import ResolveSymbol
from stock_predictor.application.instruments.service import InstrumentMasterService
from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    UnsupportedExchangeError,
)
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.exchange import ExchangeCatalog
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market.instrument import AssetClass, Instrument


def _register(service: InstrumentMasterService, name: str) -> Instrument:
    return service.register(
        RegisterInstrument(
            display_name=name,
            asset_class=AssetClass.EQUITY,
            primary_exchange_mic=MarketIdentifierCode("XNYS"),
            trading_currency=Currency("USD"),
            listing_date=date(2020, 1, 2),
        )
    )


def test_service_resolves_effective_symbol(exchange_catalog: ExchangeCatalog) -> None:
    service = InstrumentMasterService(InMemoryInstrumentRepository(), exchange_catalog)
    instrument = _register(service, "Example Corp")
    service.add_symbol_mapping(
        AddSymbolMapping(
            instrument.instrument_id,
            ProviderName("vendor"),
            TickerSymbol("EXM"),
            MarketIdentifierCode("XNYS"),
            EffectivePeriod(date(2020, 1, 2)),
        )
    )

    resolved = service.resolve_symbol(
        ResolveSymbol(
            ProviderName("vendor"),
            TickerSymbol("EXM"),
            MarketIdentifierCode("XNYS"),
            date(2026, 1, 2),
        )
    )

    assert resolved.instrument_id == instrument.instrument_id


def test_repository_rejects_global_symbol_collision(
    exchange_catalog: ExchangeCatalog,
) -> None:
    service = InstrumentMasterService(InMemoryInstrumentRepository(), exchange_catalog)
    first = _register(service, "First Corp")
    second = _register(service, "Second Corp")
    def duplicate_mapping(instrument: Instrument) -> AddSymbolMapping:
        return AddSymbolMapping(
            instrument_id=instrument.instrument_id,
            provider=ProviderName("vendor"),
            symbol=TickerSymbol("DUP"),
            exchange_mic=MarketIdentifierCode("XNYS"),
            effective_period=EffectivePeriod(date(2020, 1, 2)),
        )

    service.add_symbol_mapping(duplicate_mapping(first))

    with pytest.raises(DomainConflictError, match="more than one instrument"):
        service.add_symbol_mapping(duplicate_mapping(second))


def test_unknown_symbol_raises_explicit_error(
    exchange_catalog: ExchangeCatalog,
) -> None:
    service = InstrumentMasterService(InMemoryInstrumentRepository(), exchange_catalog)

    with pytest.raises(DomainNotFoundError, match="No instrument mapping"):
        service.resolve_symbol(
            ResolveSymbol(
                ProviderName("vendor"),
                TickerSymbol("NONE"),
                MarketIdentifierCode("XNYS"),
                date(2026, 1, 2),
            )
        )


def test_service_rejects_unconfigured_exchange(
    exchange_catalog: ExchangeCatalog,
) -> None:
    service = InstrumentMasterService(InMemoryInstrumentRepository(), exchange_catalog)

    with pytest.raises(UnsupportedExchangeError, match="not configured"):
        service.register(
            RegisterInstrument(
                display_name="Unknown Venue Corp",
                asset_class=AssetClass.EQUITY,
                primary_exchange_mic=MarketIdentifierCode("XNAS"),
                trading_currency=Currency("USD"),
                listing_date=date(2020, 1, 2),
            )
        )
