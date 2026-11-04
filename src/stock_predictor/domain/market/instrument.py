"""Instrument aggregate with effective-dated identities and symbols."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainValidationError,
    OverlappingEffectivePeriodError,
)
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.market.identifiers import (
    InstrumentIdentifier,
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market.symbol import SymbolMapping


class AssetClass(StrEnum):
    """High-level instrument classification."""

    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    FUND = "fund"
    ADR = "adr"
    OTHER = "other"


class InstrumentStatus(StrEnum):
    """Lifecycle status independent of daily trading halts."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELISTED = "delisted"


@dataclass(frozen=True, slots=True)
class Instrument:
    """Stable financial-instrument identity.

    Tickers and external identifiers are attributes with effective periods, not entity keys.
    """

    instrument_id: InstrumentId
    display_name: str
    asset_class: AssetClass
    primary_exchange_mic: MarketIdentifierCode
    trading_currency: Currency
    listing_date: date
    delisting_date: date | None = None
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    identifiers: tuple[InstrumentIdentifier, ...] = ()
    symbol_mappings: tuple[SymbolMapping, ...] = ()

    def __post_init__(self) -> None:
        normalized_name = self.display_name.strip()
        if not normalized_name:
            msg = "Instrument display name cannot be empty"
            raise DomainValidationError(msg)
        if self.delisting_date is not None and self.delisting_date <= self.listing_date:
            msg = "Delisting date must be later than listing date"
            raise DomainValidationError(msg)
        if self.status is InstrumentStatus.DELISTED and self.delisting_date is None:
            msg = "A delisted instrument requires a delisting date"
            raise DomainValidationError(msg)
        object.__setattr__(self, "display_name", normalized_name)
        self._validate_identifier_history(self.identifiers)
        self._validate_symbol_history(self.symbol_mappings)

    @staticmethod
    def _validate_identifier_history(identifiers: tuple[InstrumentIdentifier, ...]) -> None:
        for index, current in enumerate(identifiers):
            for other in identifiers[index + 1 :]:
                if (
                    current.has_same_namespace(other)
                    and current.effective_period.overlaps(other.effective_period)
                ):
                    msg = (
                        "External identifiers overlap in the same scheme/provider namespace: "
                        f"{current.scheme}"
                    )
                    raise OverlappingEffectivePeriodError(msg)

    @staticmethod
    def _validate_symbol_history(mappings: tuple[SymbolMapping, ...]) -> None:
        for index, current in enumerate(mappings):
            for other in mappings[index + 1 :]:
                if (
                    current.same_provider_venue(other)
                    and current.effective_period.overlaps(other.effective_period)
                ):
                    msg = (
                        "An instrument cannot have overlapping symbols for one provider and "
                        f"venue: {current.provider}/{current.exchange_mic}"
                    )
                    raise OverlappingEffectivePeriodError(msg)

    def is_listed_on(self, as_of: date) -> bool:
        """Return whether the instrument is within its listing interval."""
        return as_of >= self.listing_date and (
            self.delisting_date is None or as_of < self.delisting_date
        )

    def with_identifier(self, identifier: InstrumentIdentifier) -> Instrument:
        """Return a new aggregate containing an additional identifier."""
        if identifier in self.identifiers:
            msg = "Instrument identifier already exists"
            raise DomainConflictError(msg)
        return replace(self, identifiers=(*self.identifiers, identifier))

    def with_symbol_mapping(self, mapping: SymbolMapping) -> Instrument:
        """Return a new aggregate containing an additional symbol history entry."""
        if mapping in self.symbol_mappings:
            msg = "Symbol mapping already exists"
            raise DomainConflictError(msg)
        return replace(self, symbol_mappings=(*self.symbol_mappings, mapping))

    def resolve_symbol(
        self,
        provider: ProviderName,
        exchange_mic: MarketIdentifierCode,
        as_of: date,
    ) -> TickerSymbol | None:
        """Resolve the effective provider symbol for a venue and date."""
        matches = [
            mapping.symbol
            for mapping in self.symbol_mappings
            if mapping.provider == provider
            and mapping.exchange_mic == exchange_mic
            and mapping.is_effective_on(as_of)
        ]
        if len(matches) > 1:  # Defensive: aggregate validation should make this impossible.
            msg = "Multiple effective symbol mappings violate instrument invariants"
            raise DomainConflictError(msg)
        return matches[0] if matches else None
