"""Commands accepted by the instrument-master application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.identifiers import (
    InstrumentIdentifierScheme,
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market.instrument import AssetClass, InstrumentStatus


@dataclass(frozen=True, slots=True)
class RegisterInstrument:
    """Register a stable instrument identity."""

    display_name: str
    asset_class: AssetClass
    primary_exchange_mic: MarketIdentifierCode
    trading_currency: Currency
    listing_date: date
    delisting_date: date | None = None
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    instrument_id: InstrumentId | None = None


@dataclass(frozen=True, slots=True)
class AddSymbolMapping:
    """Add an effective-dated provider symbol to an instrument."""

    instrument_id: InstrumentId
    provider: ProviderName
    symbol: TickerSymbol
    exchange_mic: MarketIdentifierCode
    effective_period: EffectivePeriod


@dataclass(frozen=True, slots=True)
class AddInstrumentIdentifier:
    """Add an effective-dated external identifier to an instrument."""

    instrument_id: InstrumentId
    scheme: InstrumentIdentifierScheme
    value: str
    effective_period: EffectivePeriod
    provider: ProviderName | None = None
