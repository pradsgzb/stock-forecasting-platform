"""Market-data provider port and provider error taxonomy."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol, runtime_checkable

from stock_predictor.domain.market_data.contracts import (
    MarketDataPage,
    PriceBarRequest,
    ProviderCapabilities,
    ProviderPriceBar,
)


class MarketDataProviderError(RuntimeError):
    """Base error raised by a provider adapter."""


class TransientMarketDataProviderError(MarketDataProviderError):
    """Retryable provider failure such as throttling or a temporary outage."""

    def __init__(self, message: str, *, retry_after: timedelta | None = None) -> None:
        if retry_after is not None and retry_after < timedelta():
            raise ValueError("retry_after cannot be negative")
        super().__init__(message)
        self.retry_after = retry_after


class PermanentMarketDataProviderError(MarketDataProviderError):
    """Non-retryable provider failure such as invalid authorization or request syntax."""


@runtime_checkable
class MarketDataProvider(Protocol):
    """Fetches opaque pages and decodes only the provider payloads it owns."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the machine-checkable adapter capability declaration."""
        ...

    def fetch_price_bars(
        self, request: PriceBarRequest, *, cursor: str | None = None
    ) -> MarketDataPage:
        """Fetch one provider response page."""
        ...

    def decode_price_bars(
        self, page: MarketDataPage
    ) -> tuple[ProviderPriceBar, ...]:
        """Decode a previously preserved raw page without calling the provider again."""
        ...
