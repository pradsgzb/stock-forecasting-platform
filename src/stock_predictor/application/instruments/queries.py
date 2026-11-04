"""Queries accepted by the instrument-master application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)


@dataclass(frozen=True, slots=True)
class ResolveSymbol:
    """Resolve a provider/venue symbol at a point in time."""

    provider: ProviderName
    symbol: TickerSymbol
    exchange_mic: MarketIdentifierCode
    as_of: date
