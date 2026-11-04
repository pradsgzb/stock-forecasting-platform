"""Deterministic JSON provider used for local development and contract tests."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from stock_predictor.adapters.market_data.sdk import (
    ProviderRetryPolicy,
    ResilientMarketDataProvider,
)
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import ProviderContractError
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.common.temporal import InformationTimeline, UtcInstant
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market_data.contracts import (
    BarFrequency,
    MarketDataKind,
    MarketDataPage,
    PriceAdjustment,
    PriceBarRequest,
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderPriceBar,
    RecordOperation,
)
from stock_predictor.ports.market_data_provider import PermanentMarketDataProviderError


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


class SyntheticMarketDataProvider(ResilientMarketDataProvider):
    """In-process provider with a real serialized page boundary.

    It is not a mock: ingestion persists the exact JSON bytes and later validation decodes those
    bytes through the same provider adapter contract used by external vendors.
    """

    SCHEMA_VERSION = "synthetic.price-bars.v1"
    CONTENT_TYPE = "application/json"

    __slots__ = ("_clock", "_records")

    def __init__(
        self,
        records: tuple[ProviderPriceBar, ...],
        clock: Clock,
        *,
        retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        provider = ProviderName("synthetic")
        exchanges = frozenset(item.exchange_mic for item in records) or frozenset(
            {MarketIdentifierCode("XNYS"), MarketIdentifierCode("XBOM")}
        )
        super().__init__(
            ProviderCapabilities(
                descriptor=ProviderDescriptor(provider, "1.0.0", "Synthetic Market Data"),
                data_kinds=frozenset({MarketDataKind.PRICE_BARS}),
                exchanges=exchanges,
                frequencies=frozenset({BarFrequency.DAILY}),
                adjustments=frozenset({PriceAdjustment.RAW}),
                max_symbols_per_request=10_000,
                max_days_per_request=36_600,
                supports_pagination=True,
                supports_corrections=True,
            ),
            retry_policy=retry_policy,
        )
        if any(item.provider != provider for item in records):
            raise ProviderContractError("Synthetic records must use provider 'synthetic'")
        self._records = tuple(
            sorted(
                records,
                key=lambda item: (
                    str(item.symbol),
                    item.session_date,
                    item.revision,
                    item.provider_record_id,
                ),
            )
        )
        self._clock = clock

    def _fetch_price_bars(
        self, request: PriceBarRequest, *, cursor: str | None
    ) -> MarketDataPage:
        try:
            offset = 0 if cursor is None else int(cursor)
        except ValueError as exc:
            raise PermanentMarketDataProviderError("Synthetic cursor is invalid") from exc
        if offset < 0:
            raise PermanentMarketDataProviderError("Synthetic cursor cannot be negative")
        symbols = set(request.symbols)
        matching = tuple(
            item
            for item in self._records
            if item.exchange_mic == request.exchange_mic
            and item.symbol in symbols
            and request.start <= item.session_date <= request.end
            and item.frequency is request.frequency
        )
        selected = matching[offset : offset + request.page_size]
        next_offset = offset + len(selected)
        next_cursor = str(next_offset) if next_offset < len(matching) else None
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "request_fingerprint": request.request_fingerprint,
            "records": [self._serialize(item) for item in selected],
        }
        return MarketDataPage(
            provider=self.capabilities.descriptor.name,
            request_fingerprint=request.request_fingerprint,
            provider_request_id=f"synthetic-{request.request_fingerprint[:12]}-{offset}",
            retrieved_at=self._clock.now(),
            schema_version=self.SCHEMA_VERSION,
            content_type=self.CONTENT_TYPE,
            raw_payload=_canonical_json(payload),
            next_cursor=next_cursor,
            advertised_record_count=len(selected),
            response_metadata={"source": "deterministic-local"},
        )

    def _decode_price_bars(
        self, page: MarketDataPage
    ) -> tuple[ProviderPriceBar, ...]:
        if page.content_type != self.CONTENT_TYPE or page.schema_version != self.SCHEMA_VERSION:
            raise ProviderContractError("Unsupported synthetic payload schema or content type")
        try:
            document = json.loads(page.raw_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderContractError("Synthetic payload is not valid JSON") from exc
        if not isinstance(document, dict):
            raise ProviderContractError("Synthetic payload root must be an object")
        if document.get("schema_version") != self.SCHEMA_VERSION:
            raise ProviderContractError("Synthetic payload schema marker is invalid")
        if document.get("request_fingerprint") != page.request_fingerprint:
            raise ProviderContractError("Synthetic payload request fingerprint is invalid")
        records = document.get("records")
        if not isinstance(records, list):
            raise ProviderContractError("Synthetic payload records must be a list")
        try:
            return tuple(self._deserialize(item) for item in records)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderContractError("Synthetic payload record is invalid") from exc

    @staticmethod
    def _serialize(record: ProviderPriceBar) -> dict[str, Any]:
        values = {
            "open": None if record.open_price is None else str(record.open_price),
            "high": None if record.high_price is None else str(record.high_price),
            "low": None if record.low_price is None else str(record.low_price),
            "close": None if record.close_price is None else str(record.close_price),
            "volume": None if record.volume is None else str(record.volume),
        }
        return {
            "provider_record_id": record.provider_record_id,
            "provider": str(record.provider),
            "symbol": str(record.symbol),
            "exchange_mic": str(record.exchange_mic),
            "session_date": record.session_date.isoformat(),
            "frequency": record.frequency.value,
            "operation": record.operation.value,
            "revision": record.revision,
            "currency": str(record.currency),
            "timeline": {
                "event_time": record.timeline.event_time.isoformat(),
                "published_at": record.timeline.published_at.isoformat(),
                "received_at": record.timeline.received_at.isoformat(),
                "processed_at": record.timeline.processed_at.isoformat(),
            },
            **values,
            "metadata": dict(record.metadata),
        }

    @staticmethod
    def _deserialize(value: object) -> ProviderPriceBar:
        if not isinstance(value, dict):
            raise TypeError("record must be an object")
        timeline = value["timeline"]
        if not isinstance(timeline, dict):
            raise TypeError("timeline must be an object")
        operation = RecordOperation(str(value["operation"]))

        def decimal_or_none(name: str) -> Decimal | None:
            raw = value.get(name)
            return None if raw is None else Decimal(str(raw))

        metadata = value.get("metadata", {})
        if not isinstance(metadata, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in metadata.items()
        ):
            raise TypeError("metadata must map strings to strings")
        return ProviderPriceBar(
            provider_record_id=str(value["provider_record_id"]),
            provider=ProviderName(str(value["provider"])),
            symbol=TickerSymbol(str(value["symbol"])),
            exchange_mic=MarketIdentifierCode(str(value["exchange_mic"])),
            session_date=date.fromisoformat(str(value["session_date"])),
            frequency=BarFrequency(str(value["frequency"])),
            operation=operation,
            revision=int(value["revision"]),
            currency=Currency(str(value["currency"])),
            timeline=InformationTimeline(
                event_time=UtcInstant.parse(str(timeline["event_time"])),
                published_at=UtcInstant.parse(str(timeline["published_at"])),
                received_at=UtcInstant.parse(str(timeline["received_at"])),
                processed_at=UtcInstant.parse(str(timeline["processed_at"])),
            ),
            open_price=decimal_or_none("open"),
            high_price=decimal_or_none("high"),
            low_price=decimal_or_none("low"),
            close_price=decimal_or_none("close"),
            volume=decimal_or_none("volume"),
            metadata=metadata,
        )
