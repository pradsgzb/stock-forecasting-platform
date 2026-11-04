from datetime import date

from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
    InMemoryInstrumentRepository,
)
from stock_predictor.application.instruments.commands import (
    AddInstrumentIdentifier,
    RegisterInstrument,
)
from stock_predictor.application.instruments.service import InstrumentMasterService
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.exchange import ExchangeCatalog
from stock_predictor.domain.market.identifiers import (
    InstrumentIdentifierScheme,
    MarketIdentifierCode,
)
from stock_predictor.domain.market.instrument import AssetClass


def test_service_adds_external_identifier(exchange_catalog: ExchangeCatalog) -> None:
    service = InstrumentMasterService(InMemoryInstrumentRepository(), exchange_catalog)
    instrument = service.register(
        RegisterInstrument(
            "Example",
            AssetClass.EQUITY,
            MarketIdentifierCode("XNYS"),
            Currency("USD"),
            date(2020, 1, 1),
        )
    )

    updated = service.add_identifier(
        AddInstrumentIdentifier(
            instrument.instrument_id,
            InstrumentIdentifierScheme.ISIN,
            "US0000000001",
            EffectivePeriod(date(2020, 1, 1)),
        )
    )

    assert updated.identifiers[0].value == "US0000000001"
