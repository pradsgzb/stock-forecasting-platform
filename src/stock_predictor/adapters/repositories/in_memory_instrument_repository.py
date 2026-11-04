"""Thread-safe in-memory instrument repository for development and tests."""

from __future__ import annotations

from datetime import date
from threading import RLock

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
)
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market.instrument import Instrument


class InMemoryInstrumentRepository:
    """Stores immutable instrument aggregates and enforces global symbol uniqueness."""

    __slots__ = ("_by_id", "_lock")

    def __init__(self) -> None:
        self._by_id: dict[InstrumentId, Instrument] = {}
        self._lock = RLock()

    def _assert_symbol_uniqueness(self, candidate: Instrument) -> None:
        for existing in self._by_id.values():
            if existing.instrument_id == candidate.instrument_id:
                continue
            for proposed in candidate.symbol_mappings:
                for current in existing.symbol_mappings:
                    if (
                        proposed.same_symbol_namespace(current)
                        and proposed.effective_period.overlaps(current.effective_period)
                    ):
                        msg = (
                            "Provider symbol maps to more than one instrument during an "
                            "overlapping period: "
                            f"{proposed.provider}/{proposed.exchange_mic}/{proposed.symbol}"
                        )
                        raise DomainConflictError(msg)

    def add(self, instrument: Instrument) -> None:
        with self._lock:
            if instrument.instrument_id in self._by_id:
                msg = f"Instrument already exists: {instrument.instrument_id}"
                raise DomainConflictError(msg)
            self._assert_symbol_uniqueness(instrument)
            self._by_id[instrument.instrument_id] = instrument

    def save(self, instrument: Instrument) -> None:
        with self._lock:
            if instrument.instrument_id not in self._by_id:
                msg = f"Cannot save unknown instrument: {instrument.instrument_id}"
                raise DomainNotFoundError(msg)
            self._assert_symbol_uniqueness(instrument)
            self._by_id[instrument.instrument_id] = instrument

    def get(self, instrument_id: InstrumentId) -> Instrument:
        with self._lock:
            try:
                return self._by_id[instrument_id]
            except KeyError as exc:
                msg = f"Instrument not found: {instrument_id}"
                raise DomainNotFoundError(msg) from exc

    def find_by_symbol(
        self,
        provider: ProviderName,
        symbol: TickerSymbol,
        exchange_mic: MarketIdentifierCode,
        as_of: date,
    ) -> Instrument | None:
        with self._lock:
            matches = [
                instrument
                for instrument in self._by_id.values()
                if any(
                    mapping.provider == provider
                    and mapping.symbol == symbol
                    and mapping.exchange_mic == exchange_mic
                    and mapping.is_effective_on(as_of)
                    for mapping in instrument.symbol_mappings
                )
            ]
        if len(matches) > 1:
            msg = (
                "Repository contains an ambiguous provider symbol mapping: "
                f"{provider}/{exchange_mic}/{symbol} on {as_of}"
            )
            raise DomainConflictError(msg)
        return matches[0] if matches else None

    def list_all(self) -> tuple[Instrument, ...]:
        with self._lock:
            return tuple(sorted(self._by_id.values(), key=lambda item: str(item.instrument_id)))
