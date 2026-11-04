"""Exchange identity and explicit calendar configuration."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainValidationError,
    UnsupportedExchangeError,
)
from stock_predictor.domain.market.identifiers import CountryCode, MarketIdentifierCode


@dataclass(frozen=True, slots=True)
class Exchange:
    """Trading venue with an explicit IANA time zone and calendar adapter name."""

    mic: MarketIdentifierCode
    name: str
    country_code: CountryCode
    timezone_name: str
    calendar_name: str | None

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            msg = "Exchange name cannot be empty"
            raise DomainValidationError(msg)
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            msg = f"Unknown IANA time zone: {self.timezone_name!r}"
            raise DomainValidationError(msg) from exc
        if self.calendar_name is not None and not self.calendar_name.strip():
            msg = "Calendar name cannot be blank"
            raise DomainValidationError(msg)
        object.__setattr__(self, "name", normalized_name)
        if self.calendar_name is not None:
            object.__setattr__(self, "calendar_name", self.calendar_name.strip().upper())

    @property
    def timezone(self) -> ZoneInfo:
        """Return this exchange's IANA time zone."""
        return ZoneInfo(self.timezone_name)


class ExchangeCatalog:
    """Immutable catalog of configured exchanges."""

    __slots__ = ("_by_mic",)

    def __init__(self, exchanges: tuple[Exchange, ...]) -> None:
        by_mic: dict[MarketIdentifierCode, Exchange] = {}
        for exchange in exchanges:
            if exchange.mic in by_mic:
                msg = f"Duplicate exchange MIC: {exchange.mic}"
                raise DomainConflictError(msg)
            by_mic[exchange.mic] = exchange
        if not by_mic:
            msg = "Exchange catalog cannot be empty"
            raise DomainValidationError(msg)
        self._by_mic = MappingProxyType(by_mic)

    def get(self, mic: MarketIdentifierCode) -> Exchange:
        """Return a configured exchange or fail explicitly."""
        try:
            return self._by_mic[mic]
        except KeyError as exc:
            msg = f"Exchange is not configured: {mic}"
            raise UnsupportedExchangeError(msg) from exc

    def all(self) -> tuple[Exchange, ...]:
        return tuple(self._by_mic.values())
