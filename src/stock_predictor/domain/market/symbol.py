"""Effective-dated provider symbol mappings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)


@dataclass(frozen=True, slots=True)
class SymbolMapping:
    """Maps a provider symbol and venue to an instrument for a period."""

    provider: ProviderName
    symbol: TickerSymbol
    exchange_mic: MarketIdentifierCode
    effective_period: EffectivePeriod

    def is_effective_on(self, as_of: date) -> bool:
        return self.effective_period.contains(as_of)

    def same_provider_venue(self, other: SymbolMapping) -> bool:
        return self.provider == other.provider and self.exchange_mic == other.exchange_mic

    def same_symbol_namespace(self, other: SymbolMapping) -> bool:
        return self.same_provider_venue(other) and self.symbol == other.symbol
