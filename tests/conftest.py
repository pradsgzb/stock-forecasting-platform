"""Shared test fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.exchange import Exchange, ExchangeCatalog
from stock_predictor.domain.market.identifiers import (
    CountryCode,
    MarketIdentifierCode,
)
from stock_predictor.domain.market.instrument import AssetClass, Instrument


@pytest.fixture
def usd() -> Currency:
    return Currency("USD")


@pytest.fixture
def xnys() -> MarketIdentifierCode:
    return MarketIdentifierCode("XNYS")


@pytest.fixture
def exchange_catalog() -> ExchangeCatalog:
    return ExchangeCatalog(
        (
            Exchange(
                mic=MarketIdentifierCode("XNYS"),
                name="New York Stock Exchange",
                country_code=CountryCode("US"),
                timezone_name="America/New_York",
                calendar_name="XNYS",
            ),
        )
    )


@pytest.fixture
def sample_instrument(usd: Currency, xnys: MarketIdentifierCode) -> Instrument:
    return Instrument(
        instrument_id=InstrumentId.new(),
        display_name="Example Corporation",
        asset_class=AssetClass.EQUITY,
        primary_exchange_mic=xnys,
        trading_currency=usd,
        listing_date=date(2020, 1, 2),
    )


@pytest.fixture
def fixed_instant() -> UtcInstant:
    return UtcInstant(datetime(2026, 1, 2, 15, 30, tzinfo=UTC))


@pytest.fixture
def synthetic_provider_name():
    from stock_predictor.domain.market.identifiers import ProviderName

    return ProviderName("synthetic")


@pytest.fixture
def sample_symbol():
    from stock_predictor.domain.market.identifiers import TickerSymbol

    return TickerSymbol("TEST")


@pytest.fixture
def make_provider_bar(synthetic_provider_name, sample_symbol, xnys, usd):
    from datetime import timedelta

    from stock_predictor.domain.common.temporal import InformationTimeline
    from stock_predictor.domain.market_data.contracts import (
        BarFrequency,
        ProviderPriceBar,
        RecordOperation,
    )

    def factory(
        session_date=date(2025, 7, 2),
        *,
        symbol=sample_symbol,
        provider=synthetic_provider_name,
        exchange_mic=xnys,
        revision=0,
        operation=RecordOperation.UPSERT,
        open_price="100",
        high_price="105",
        low_price="99",
        close_price="103",
        volume="1000",
        processed_delay_minutes=3,
        provider_record_id=None,
    ):
        event = UtcInstant(
            datetime(
                session_date.year,
                session_date.month,
                session_date.day,
                20,
                0,
                tzinfo=UTC,
            )
        )
        timeline = InformationTimeline(
            event_time=event,
            published_at=event.plus(timedelta(minutes=1)),
            received_at=event.plus(timedelta(minutes=2)),
            processed_at=event.plus(timedelta(minutes=processed_delay_minutes)),
        )
        if operation is RecordOperation.DELETE:
            open_price = high_price = low_price = close_price = volume = None
        return ProviderPriceBar(
            provider_record_id=provider_record_id or f"{symbol}-{session_date}-r{revision}",
            provider=provider,
            symbol=symbol,
            exchange_mic=exchange_mic,
            session_date=session_date,
            frequency=BarFrequency.DAILY,
            operation=operation,
            revision=revision,
            currency=usd,
            timeline=timeline,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
            metadata={"fixture": "true"},
        )

    return factory


@pytest.fixture
def mapped_instrument_repository(
    sample_instrument,
    synthetic_provider_name,
    sample_symbol,
    xnys,
):
    from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
        InMemoryInstrumentRepository,
    )
    from stock_predictor.domain.common.temporal import EffectivePeriod
    from stock_predictor.domain.market.symbol import SymbolMapping

    repository = InMemoryInstrumentRepository()
    mapped = sample_instrument.with_symbol_mapping(
        SymbolMapping(
            synthetic_provider_name,
            sample_symbol,
            xnys,
            EffectivePeriod(sample_instrument.listing_date),
        )
    )
    repository.add(mapped)
    return repository, mapped


@pytest.fixture
def operational_store(tmp_path):
    from stock_predictor.adapters.persistence.sqlalchemy_store import (
        SqlAlchemyOperationalStore,
    )

    store = SqlAlchemyOperationalStore(f"sqlite+pysqlite:///{tmp_path / 'operations.db'}")
    store.create_schema_for_testing()
    try:
        yield store
    finally:
        store.dispose()


@pytest.fixture
def operator_principal():
    from stock_predictor.domain.security.identity import Principal, PrincipalRole

    return Principal(
        "operator-1",
        "Research Operator",
        frozenset(
            {
                PrincipalRole.VIEWER,
                PrincipalRole.OPERATOR,
                PrincipalRole.AUDITOR,
                PrincipalRole.METRICS_READER,
            }
        ),
    )
