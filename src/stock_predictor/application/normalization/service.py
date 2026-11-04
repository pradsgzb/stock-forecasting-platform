"""Convert accepted provider records into append-only canonical price-bar revisions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from stock_predictor.application.quality.models import ValidatedPriceBarBatch
from stock_predictor.domain.common.errors import DataQualityGateError, DomainConflictError
from stock_predictor.domain.common.identifiers import InstrumentId, PriceBarId
from stock_predictor.domain.common.money import Price
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.market_data.contracts import (
    BarFrequency,
    ProviderPriceBar,
    RecordOperation,
)
from stock_predictor.domain.market_data.point_in_time import (
    NormalizedPriceBar,
    PriceBarKey,
    PriceBarValues,
)
from stock_predictor.ports.instrument_repository import InstrumentRepository
from stock_predictor.ports.price_bar_repository import PriceBarRepository


@dataclass(frozen=True, slots=True)
class NormalizedPriceBarBatch:
    validation_report_fingerprint: str
    bars: tuple[NormalizedPriceBar, ...]


class PriceBarNormalizationService:
    """Resolves symbols and appends deterministic canonical source revisions."""

    __slots__ = ("_bars", "_instruments")

    def __init__(
        self, instruments: InstrumentRepository, bars: PriceBarRepository
    ) -> None:
        self._instruments = instruments
        self._bars = bars

    @staticmethod
    def _bar_id(
        *,
        provider: str,
        provider_record_id: str,
        provider_revision: int,
        instrument_id: InstrumentId,
        session_date: str,
        frequency: BarFrequency,
    ) -> PriceBarId:
        """Build identity from provider semantics, never page layout or storage location."""
        seed = "|".join(
            (
                provider,
                provider_record_id,
                str(provider_revision),
                str(instrument_id),
                session_date,
                frequency.value,
            )
        )
        return PriceBarId(uuid5(NAMESPACE_URL, f"stock-predictor:price-bar:{seed}"))

    @staticmethod
    def _values(record: ProviderPriceBar) -> PriceBarValues | None:
        if record.operation is RecordOperation.DELETE:
            return None
        if any(
            value is None
            for value in (
                record.open_price,
                record.high_price,
                record.low_price,
                record.close_price,
                record.volume,
            )
        ):
            raise DataQualityGateError("Accepted upsert unexpectedly has missing values")
        return PriceBarValues(
            open_price=Price(record.open_price, record.currency),
            high_price=Price(record.high_price, record.currency),
            low_price=Price(record.low_price, record.currency),
            close_price=Price(record.close_price, record.currency),
            volume=Quantity(record.volume),
        )

    @staticmethod
    def _matches_existing(
        existing: NormalizedPriceBar,
        *,
        key: PriceBarKey,
        record: ProviderPriceBar,
        values: PriceBarValues | None,
    ) -> bool:
        """Compare provider semantics while allowing equivalent repagination."""
        return (
            existing.key == key
            and existing.provider == record.provider
            and existing.provider_record_id == record.provider_record_id
            and existing.provider_revision == record.revision
            and existing.operation is record.operation
            and existing.values == values
            and existing.timeline == record.timeline
        )

    def normalize(self, batch: ValidatedPriceBarBatch) -> NormalizedPriceBarBatch:
        batch.require_accepted()
        normalized: list[NormalizedPriceBar] = []
        for decoded in batch.records:
            record = decoded.record
            instrument = self._instruments.find_by_symbol(
                provider=record.provider,
                symbol=record.symbol,
                exchange_mic=record.exchange_mic,
                as_of=record.session_date,
            )
            if instrument is None:
                raise DataQualityGateError(
                    "Cannot normalize a provider symbol without a point-in-time "
                    "instrument mapping: "
                    f"{record.provider}/{record.exchange_mic}/{record.symbol}/"
                    f"{record.session_date}"
                )
            if instrument.trading_currency != record.currency:
                raise DataQualityGateError(
                    f"Provider currency {record.currency} does not match instrument currency "
                    f"{instrument.trading_currency}"
                )
            key = PriceBarKey(
                instrument_id=instrument.instrument_id,
                exchange_mic=record.exchange_mic,
                session_date=record.session_date,
                frequency=record.frequency,
            )
            values = self._values(record)
            identifier = self._bar_id(
                provider=str(record.provider),
                provider_record_id=record.provider_record_id,
                provider_revision=record.revision,
                instrument_id=instrument.instrument_id,
                session_date=record.session_date.isoformat(),
                frequency=record.frequency,
            )
            history = self._bars.history(key)
            existing = next((item for item in history if item.bar_id == identifier), None)
            if existing is not None:
                if not self._matches_existing(
                    existing,
                    key=key,
                    record=record,
                    values=values,
                ):
                    raise DomainConflictError(
                        "Provider reused a price-bar identity with different content"
                    )
                normalized.append(existing)
                continue
            if any(item.provider_revision == record.revision for item in history):
                raise DomainConflictError(
                    "Provider revision conflicts with an existing canonical price-bar history"
                )
            predecessor = max(
                (item for item in history if item.provider_revision < record.revision),
                key=lambda item: item.provider_revision,
                default=None,
            )
            if history and predecessor is None:
                raise DomainConflictError(
                    "Provider revision conflicts with an existing canonical price-bar history"
                )
            normalized_at = UtcInstant(
                max(
                    batch.report.generated_at.value,
                    record.timeline.processed_at.value,
                    batch.manifest.completed_at.value,
                )
            )
            bar = NormalizedPriceBar(
                bar_id=identifier,
                key=key,
                provider=record.provider,
                provider_record_id=record.provider_record_id,
                provider_revision=record.revision,
                operation=record.operation,
                values=values,
                timeline=record.timeline,
                normalized_at=normalized_at,
                source_digest=decoded.source_digest,
                source_page_number=decoded.page_number,
                source_record_index=decoded.record_index,
                supersedes_bar_id=None if predecessor is None else predecessor.bar_id,
            )
            self._bars.append(bar)
            normalized.append(bar)
        return NormalizedPriceBarBatch(batch.report.report_fingerprint, tuple(normalized))
