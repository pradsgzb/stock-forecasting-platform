"""Port for instrument-master persistence."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market.instrument import Instrument


@runtime_checkable
class InstrumentRepository(Protocol):
    """Persists immutable instrument aggregates."""

    def add(self, instrument: Instrument) -> None:
        """Add a new instrument, rejecting identity or symbol conflicts."""
        ...

    def save(self, instrument: Instrument) -> None:
        """Replace an existing aggregate after validating global constraints."""
        ...

    def get(self, instrument_id: InstrumentId) -> Instrument:
        """Return an instrument or raise `DomainNotFoundError`."""
        ...

    def find_by_symbol(
        self,
        provider: ProviderName,
        symbol: TickerSymbol,
        exchange_mic: MarketIdentifierCode,
        as_of: date,
    ) -> Instrument | None:
        """Resolve a symbol to an instrument at an explicit date."""
        ...

    def list_all(self) -> tuple[Instrument, ...]:
        """Return a deterministic snapshot of all instruments."""
        ...
