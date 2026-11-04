"""Point-in-time-correct normalized price bars and adjustment factors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import AdjustmentFactorId, InstrumentId, PriceBarId
from stock_predictor.domain.common.money import Currency, Price
from stock_predictor.domain.common.temporal import InformationTimeline, UtcInstant
from stock_predictor.domain.common.values import DecimalInput, Quantity, to_decimal
from stock_predictor.domain.market.identifiers import MarketIdentifierCode, ProviderName
from stock_predictor.domain.market_data.contracts import BarFrequency, RecordOperation
from stock_predictor.domain.market_data.ingestion import Sha256Digest


@dataclass(frozen=True, slots=True, order=True)
class PriceBarKey:
    instrument_id: InstrumentId
    exchange_mic: MarketIdentifierCode
    session_date: date
    frequency: BarFrequency


@dataclass(frozen=True, slots=True)
class PriceBarValues:
    open_price: Price
    high_price: Price
    low_price: Price
    close_price: Price
    volume: Quantity

    def __post_init__(self) -> None:
        currencies = {
            self.open_price.currency,
            self.high_price.currency,
            self.low_price.currency,
            self.close_price.currency,
        }
        if len(currencies) != 1:
            raise DomainValidationError("OHLC prices must use one currency")
        if self.low_price > self.high_price:
            raise DomainValidationError("Low price cannot exceed high price")
        if self.open_price < self.low_price or self.open_price > self.high_price:
            raise DomainValidationError("Open price must fall within low and high")
        if self.close_price < self.low_price or self.close_price > self.high_price:
            raise DomainValidationError("Close price must fall within low and high")

    @property
    def currency(self) -> Currency:
        return self.close_price.currency


@dataclass(frozen=True, slots=True)
class NormalizedPriceBar:
    """Immutable normalized revision with full source and availability lineage."""

    bar_id: PriceBarId
    key: PriceBarKey
    provider: ProviderName
    provider_record_id: str
    provider_revision: int
    operation: RecordOperation
    values: PriceBarValues | None
    timeline: InformationTimeline
    normalized_at: UtcInstant
    source_digest: Sha256Digest
    source_page_number: int
    source_record_index: int
    supersedes_bar_id: PriceBarId | None = None
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.provider_revision < 0:
            raise DomainValidationError("Provider revision cannot be negative")
        if self.source_page_number <= 0 or self.source_record_index < 0:
            raise DomainValidationError("Source page and row positions are invalid")
        if self.normalized_at < self.timeline.processed_at:
            raise DomainValidationError("Normalization cannot precede source processing")
        if self.operation is RecordOperation.UPSERT and self.values is None:
            raise DomainValidationError("Normalized upsert requires values")
        if self.operation is RecordOperation.DELETE and self.values is not None:
            raise DomainValidationError("Normalized tombstone cannot contain values")
        value_parts: tuple[str, ...]
        if self.values is None:
            value_parts = ("tombstone",)
        else:
            value_parts = (
                str(self.values.open_price.amount),
                str(self.values.high_price.amount),
                str(self.values.low_price.amount),
                str(self.values.close_price.amount),
                str(self.values.volume.value),
                str(self.values.currency),
            )
        payload = "|".join(
            (
                str(self.bar_id),
                str(self.key.instrument_id),
                str(self.key.exchange_mic),
                self.key.session_date.isoformat(),
                self.key.frequency.value,
                str(self.provider),
                self.provider_record_id,
                str(self.provider_revision),
                self.operation.value,
                self.timeline.event_time.isoformat(),
                self.timeline.published_at.isoformat(),
                self.timeline.received_at.isoformat(),
                self.timeline.processed_at.isoformat(),
                self.normalized_at.isoformat(),
                str(self.source_digest),
                str(self.source_page_number),
                str(self.source_record_index),
                "" if self.supersedes_bar_id is None else str(self.supersedes_bar_id),
                *value_parts,
            )
        ).encode("utf-8")
        object.__setattr__(self, "fingerprint", hashlib.sha256(payload).hexdigest())

    @property
    def is_tombstone(self) -> bool:
        return self.operation is RecordOperation.DELETE

    def available_by(self, cutoff: UtcInstant) -> bool:
        return self.normalized_at <= cutoff and self.timeline.available_by(cutoff)


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    """Point-in-time revision of a derived corporate-action adjustment factor.

    Multiplying a historical raw price by ``price_multiplier`` and volume by
    ``volume_multiplier`` yields the selected adjusted representation. Raw bars remain unchanged.
    """

    factor_id: AdjustmentFactorId
    instrument_id: InstrumentId
    effective_on: date
    price_multiplier: Decimal
    volume_multiplier: Decimal
    revision: int
    timeline: InformationTimeline
    provider: ProviderName
    source_digest: Sha256Digest

    def __init__(
        self,
        factor_id: AdjustmentFactorId,
        instrument_id: InstrumentId,
        effective_on: date,
        price_multiplier: DecimalInput,
        volume_multiplier: DecimalInput,
        revision: int,
        timeline: InformationTimeline,
        provider: ProviderName,
        source_digest: Sha256Digest,
    ) -> None:
        price = to_decimal(price_multiplier, field_name="price multiplier")
        volume = to_decimal(volume_multiplier, field_name="volume multiplier")
        if price <= 0 or volume <= 0:
            raise DomainValidationError("Adjustment multipliers must be positive")
        if revision < 0:
            raise DomainValidationError("Adjustment revision cannot be negative")
        object.__setattr__(self, "factor_id", factor_id)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "effective_on", effective_on)
        object.__setattr__(self, "price_multiplier", price)
        object.__setattr__(self, "volume_multiplier", volume)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "timeline", timeline)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "source_digest", source_digest)

    def available_by(self, cutoff: UtcInstant) -> bool:
        return self.timeline.available_by(cutoff)
