"""Validated market identifiers and symbols."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import EffectivePeriod

_MIC_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
_COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/\-]{0,31}$")
_PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,63}$")


@dataclass(frozen=True, slots=True, order=True)
class MarketIdentifierCode:
    """ISO 10383-style four-character market identifier code."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper()
        if not _MIC_PATTERN.fullmatch(normalized):
            msg = f"Invalid market identifier code: {self.value!r}"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class CountryCode:
    """ISO 3166-1 alpha-2 country code shape."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper()
        if not _COUNTRY_PATTERN.fullmatch(normalized):
            msg = f"Invalid country code: {self.value!r}"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class ProviderName:
    """Canonical provider key used in mappings and configuration."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().casefold()
        if not _PROVIDER_PATTERN.fullmatch(normalized):
            msg = f"Invalid provider name: {self.value!r}"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class TickerSymbol:
    """Provider/venue symbol; never used as stable instrument identity."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(normalized):
            msg = f"Invalid ticker symbol: {self.value!r}"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


class InstrumentIdentifierScheme(StrEnum):
    """Supported external instrument identifier schemes."""

    ISIN = "isin"
    FIGI = "figi"
    CUSIP = "cusip"
    SEDOL = "sedol"
    RIC = "ric"
    PROVIDER = "provider"


@dataclass(frozen=True, slots=True)
class InstrumentIdentifier:
    """Effective-dated external identifier."""

    scheme: InstrumentIdentifierScheme
    value: str
    effective_period: EffectivePeriod
    provider: ProviderName | None = None

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper()
        if not normalized or len(normalized) > 64:
            msg = "Instrument identifier must contain 1 to 64 characters"
            raise DomainValidationError(msg)
        if self.scheme is InstrumentIdentifierScheme.PROVIDER and self.provider is None:
            msg = "Provider-specific identifier requires a provider"
            raise DomainValidationError(msg)
        if self.scheme is not InstrumentIdentifierScheme.PROVIDER and self.provider is not None:
            msg = "Provider namespace is only valid for provider-specific identifiers"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)

    def has_same_namespace(self, other: InstrumentIdentifier) -> bool:
        """Return whether two identifiers compete in the same effective namespace."""
        return self.scheme is other.scheme and self.provider == other.provider
