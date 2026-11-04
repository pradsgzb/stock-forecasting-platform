"""Vendor-neutral market-data request, capability, page, and record contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from stock_predictor.domain.common.errors import DomainValidationError, ProviderContractError
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.common.temporal import InformationTimeline, UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class MarketDataKind(StrEnum):
    """Market-data families understood by the provider SDK."""

    PRICE_BARS = "price_bars"
    CORPORATE_ACTIONS = "corporate_actions"
    FUNDAMENTALS = "fundamentals"
    ECONOMIC = "economic"
    NEWS = "news"


class BarFrequency(StrEnum):
    """Canonical bar frequencies; providers map their own vocabulary to these values."""

    DAILY = "1d"
    HOURLY = "1h"
    MINUTE = "1m"


class PriceAdjustment(StrEnum):
    """Requested provider adjustment policy."""

    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN_ADJUSTED = "total_return_adjusted"


class RecordOperation(StrEnum):
    """Whether a provider record adds/revises data or tombstones prior data."""

    UPSERT = "upsert"
    DELETE = "delete"


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PriceBarRequest:
    """Immutable, fingerprinted request for provider price-bar pages."""

    provider: ProviderName
    exchange_mic: MarketIdentifierCode
    symbols: tuple[TickerSymbol, ...]
    start: date
    end: date
    frequency: BarFrequency = BarFrequency.DAILY
    adjustment: PriceAdjustment = PriceAdjustment.RAW
    page_size: int = 1_000
    request_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.end < self.start:
            msg = "Price-bar request end cannot be earlier than start"
            raise DomainValidationError(msg)
        if not self.symbols:
            msg = "Price-bar request requires at least one symbol"
            raise DomainValidationError(msg)
        ordered = tuple(sorted(set(self.symbols), key=str))
        if len(ordered) != len(self.symbols):
            msg = "Price-bar request symbols must be unique"
            raise DomainValidationError(msg)
        if not 1 <= self.page_size <= 100_000:
            msg = "Price-bar request page_size must be between 1 and 100000"
            raise DomainValidationError(msg)
        object.__setattr__(self, "symbols", ordered)
        payload = {
            "provider": str(self.provider),
            "exchange_mic": str(self.exchange_mic),
            "symbols": [str(item) for item in ordered],
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "frequency": self.frequency.value,
            "adjustment": self.adjustment.value,
            "page_size": self.page_size,
        }
        object.__setattr__(
            self, "request_fingerprint", hashlib.sha256(_canonical_json(payload)).hexdigest()
        )


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Stable identity and implementation version for a market-data adapter."""

    name: ProviderName
    adapter_version: str
    display_name: str

    def __post_init__(self) -> None:
        version = self.adapter_version.strip()
        display_name = self.display_name.strip()
        if not version or not display_name:
            msg = "Provider adapter version and display name cannot be empty"
            raise DomainValidationError(msg)
        object.__setattr__(self, "adapter_version", version)
        object.__setattr__(self, "display_name", display_name)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Machine-checkable provider behavior used before any network call."""

    descriptor: ProviderDescriptor
    data_kinds: frozenset[MarketDataKind]
    exchanges: frozenset[MarketIdentifierCode]
    frequencies: frozenset[BarFrequency]
    adjustments: frozenset[PriceAdjustment]
    max_symbols_per_request: int
    max_days_per_request: int
    supports_pagination: bool = True
    supports_corrections: bool = True

    def __post_init__(self) -> None:
        if (
            not self.data_kinds
            or not self.exchanges
            or not self.frequencies
            or not self.adjustments
        ):
            msg = "Provider capabilities require kinds, exchanges, frequencies, and adjustments"
            raise DomainValidationError(msg)
        if self.max_symbols_per_request <= 0 or self.max_days_per_request <= 0:
            msg = "Provider capability limits must be positive"
            raise DomainValidationError(msg)

    def validate(self, request: PriceBarRequest) -> None:
        """Reject an unsupported request before credentials or rate limits are consumed."""
        if request.provider != self.descriptor.name:
            msg = f"Request provider {request.provider} does not match {self.descriptor.name}"
            raise ProviderContractError(msg)
        if MarketDataKind.PRICE_BARS not in self.data_kinds:
            raise ProviderContractError("Provider does not support price bars")
        if request.exchange_mic not in self.exchanges:
            msg = f"Provider does not support exchange {request.exchange_mic}"
            raise ProviderContractError(msg)
        if request.frequency not in self.frequencies:
            msg = f"Provider does not support frequency {request.frequency}"
            raise ProviderContractError(msg)
        if request.adjustment not in self.adjustments:
            msg = f"Provider does not support adjustment {request.adjustment}"
            raise ProviderContractError(msg)
        if len(request.symbols) > self.max_symbols_per_request:
            msg = "Request exceeds provider symbol limit"
            raise ProviderContractError(msg)
        day_count = (request.end - request.start).days + 1
        if day_count > self.max_days_per_request:
            msg = "Request exceeds provider date-range limit"
            raise ProviderContractError(msg)


@dataclass(frozen=True, slots=True)
class ProviderPriceBar:
    """Provider-shaped price bar decoded from a preserved raw payload.

    Business-quality invariants such as positive prices and OHLC consistency are intentionally
    evaluated by the quality pipeline rather than silently repaired in this transport record.
    """

    provider_record_id: str
    provider: ProviderName
    symbol: TickerSymbol
    exchange_mic: MarketIdentifierCode
    session_date: date
    frequency: BarFrequency
    operation: RecordOperation
    revision: int
    currency: Currency
    timeline: InformationTimeline
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    close_price: Decimal | None = None
    volume: Decimal | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __init__(
        self,
        provider_record_id: str,
        provider: ProviderName,
        symbol: TickerSymbol,
        exchange_mic: MarketIdentifierCode,
        session_date: date,
        frequency: BarFrequency,
        operation: RecordOperation,
        revision: int,
        currency: Currency,
        timeline: InformationTimeline,
        open_price: DecimalInput | None = None,
        high_price: DecimalInput | None = None,
        low_price: DecimalInput | None = None,
        close_price: DecimalInput | None = None,
        volume: DecimalInput | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        record_id = provider_record_id.strip()
        if not record_id or len(record_id) > 256:
            msg = "Provider record ID must contain 1 to 256 characters"
            raise DomainValidationError(msg)
        if revision < 0:
            msg = "Provider record revision cannot be negative"
            raise DomainValidationError(msg)
        values = (open_price, high_price, low_price, close_price, volume)
        if operation is RecordOperation.UPSERT and any(value is None for value in values):
            msg = "Upsert price bars require OHLC and volume values"
            raise DomainValidationError(msg)
        if operation is RecordOperation.DELETE and any(value is not None for value in values):
            msg = "Delete price bars must not carry OHLC or volume values"
            raise DomainValidationError(msg)
        object.__setattr__(self, "provider_record_id", record_id)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "exchange_mic", exchange_mic)
        object.__setattr__(self, "session_date", session_date)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "timeline", timeline)
        object.__setattr__(
            self,
            "open_price",
            None if open_price is None else to_decimal(open_price, field_name="open price"),
        )
        object.__setattr__(
            self,
            "high_price",
            None if high_price is None else to_decimal(high_price, field_name="high price"),
        )
        object.__setattr__(
            self,
            "low_price",
            None if low_price is None else to_decimal(low_price, field_name="low price"),
        )
        object.__setattr__(
            self,
            "close_price",
            None if close_price is None else to_decimal(close_price, field_name="close price"),
        )
        object.__setattr__(
            self, "volume", None if volume is None else to_decimal(volume, field_name="volume")
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(metadata or {})))

    @property
    def natural_key(
        self,
    ) -> tuple[ProviderName, MarketIdentifierCode, TickerSymbol, date, BarFrequency]:
        return (
            self.provider,
            self.exchange_mic,
            self.symbol,
            self.session_date,
            self.frequency,
        )


@dataclass(frozen=True, slots=True)
class MarketDataPage:
    """One opaque provider response page plus non-sensitive response metadata."""

    provider: ProviderName
    request_fingerprint: str
    provider_request_id: str
    retrieved_at: UtcInstant
    schema_version: str
    content_type: str
    raw_payload: bytes
    next_cursor: str | None
    advertised_record_count: int | None
    response_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.raw_payload:
            raise DomainValidationError("Provider page payload cannot be empty")
        normalized_fingerprint = self.request_fingerprint.strip().lower()
        if not _SHA256_PATTERN.fullmatch(normalized_fingerprint):
            raise DomainValidationError("Provider page request fingerprint must be SHA-256")
        if not self.provider_request_id.strip():
            raise DomainValidationError("Provider request ID cannot be empty")
        if not self.schema_version.strip() or not self.content_type.strip():
            raise DomainValidationError(
                "Provider page schema version and content type are required"
            )
        if self.advertised_record_count is not None and self.advertised_record_count < 0:
            raise DomainValidationError("Advertised record count cannot be negative")
        object.__setattr__(self, "request_fingerprint", normalized_fingerprint)
        object.__setattr__(self, "provider_request_id", self.provider_request_id.strip())
        object.__setattr__(self, "schema_version", self.schema_version.strip())
        object.__setattr__(self, "content_type", self.content_type.strip().lower())
        object.__setattr__(
            self, "response_metadata", MappingProxyType(dict(self.response_metadata))
        )

    @property
    def payload_digest(self) -> str:
        return hashlib.sha256(self.raw_payload).hexdigest()
