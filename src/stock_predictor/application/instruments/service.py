"""Instrument-master application service."""

from __future__ import annotations

from stock_predictor.application.instruments.commands import (
    AddInstrumentIdentifier,
    AddSymbolMapping,
    RegisterInstrument,
)
from stock_predictor.application.instruments.queries import ResolveSymbol
from stock_predictor.domain.common.errors import DomainNotFoundError
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.market.exchange import ExchangeCatalog
from stock_predictor.domain.market.identifiers import InstrumentIdentifier
from stock_predictor.domain.market.instrument import Instrument
from stock_predictor.domain.market.symbol import SymbolMapping
from stock_predictor.ports.instrument_repository import InstrumentRepository


class InstrumentMasterService:
    """Coordinates instrument-master use cases without infrastructure knowledge."""

    __slots__ = ("_exchanges", "_repository")

    def __init__(
        self,
        repository: InstrumentRepository,
        exchanges: ExchangeCatalog,
    ) -> None:
        self._repository = repository
        self._exchanges = exchanges

    def register(self, command: RegisterInstrument) -> Instrument:
        """Register and persist a new instrument."""
        self._exchanges.get(command.primary_exchange_mic)
        instrument = Instrument(
            instrument_id=command.instrument_id or InstrumentId.new(),
            display_name=command.display_name,
            asset_class=command.asset_class,
            primary_exchange_mic=command.primary_exchange_mic,
            trading_currency=command.trading_currency,
            listing_date=command.listing_date,
            delisting_date=command.delisting_date,
            status=command.status,
        )
        self._repository.add(instrument)
        return instrument

    def add_symbol_mapping(self, command: AddSymbolMapping) -> Instrument:
        """Append a validated symbol mapping and persist the new aggregate version."""
        self._exchanges.get(command.exchange_mic)
        instrument = self._repository.get(command.instrument_id)
        updated = instrument.with_symbol_mapping(
            SymbolMapping(
                provider=command.provider,
                symbol=command.symbol,
                exchange_mic=command.exchange_mic,
                effective_period=command.effective_period,
            )
        )
        self._repository.save(updated)
        return updated

    def add_identifier(self, command: AddInstrumentIdentifier) -> Instrument:
        """Append a validated external identifier."""
        instrument = self._repository.get(command.instrument_id)
        updated = instrument.with_identifier(
            InstrumentIdentifier(
                scheme=command.scheme,
                value=command.value,
                effective_period=command.effective_period,
                provider=command.provider,
            )
        )
        self._repository.save(updated)
        return updated

    def resolve_symbol(self, query: ResolveSymbol) -> Instrument:
        """Resolve an effective provider symbol or raise an explicit not-found error."""
        self._exchanges.get(query.exchange_mic)
        instrument = self._repository.find_by_symbol(
            provider=query.provider,
            symbol=query.symbol,
            exchange_mic=query.exchange_mic,
            as_of=query.as_of,
        )
        if instrument is None:
            msg = (
                "No instrument mapping found for "
                f"{query.provider}/{query.exchange_mic}/{query.symbol} on {query.as_of}"
            )
            raise DomainNotFoundError(msg)
        return instrument
