from datetime import date, timedelta

import pytest

from stock_predictor.adapters.market_data.sdk import (
    SlidingWindowRateLimiter,
    ProviderRetryPolicy,
    ResilientMarketDataProvider,
)
from stock_predictor.domain.common.errors import DomainValidationError, ProviderContractError
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
)
from stock_predictor.ports.market_data_provider import TransientMarketDataProviderError


class StubProvider(ResilientMarketDataProvider):
    def __init__(self, fixed_instant, failures=0, **kwargs):
        self.fixed_instant = fixed_instant
        self.failures = failures
        self.calls = 0
        super().__init__(
            ProviderCapabilities(
                ProviderDescriptor(ProviderName("stub"), "1", "Stub"),
                frozenset({MarketDataKind.PRICE_BARS}),
                frozenset({MarketIdentifierCode("XNYS")}),
                frozenset({BarFrequency.DAILY}),
                frozenset({PriceAdjustment.RAW}),
                10,
                10,
            ),
            **kwargs,
        )

    def _fetch_price_bars(self, request, *, cursor):
        self.calls += 1
        if self.calls <= self.failures:
            raise TransientMarketDataProviderError(
                "temporary", retry_after=timedelta(milliseconds=10)
            )
        return MarketDataPage(
            ProviderName("stub"),
            request.request_fingerprint,
            "request",
            self.fixed_instant,
            "v1",
            "application/json",
            b"{}",
            None,
            0,
        )

    def _decode_price_bars(self, page):
        return ()


def _request() -> PriceBarRequest:
    return PriceBarRequest(
        ProviderName("stub"),
        MarketIdentifierCode("XNYS"),
        (TickerSymbol("AAA"),),
        date(2025, 1, 1),
        date(2025, 1, 2),
    )


def test_retry_policy_is_bounded_and_validated() -> None:
    policy = ProviderRetryPolicy(
        max_attempts=3,
        initial_delay=timedelta(seconds=1),
        maximum_delay=timedelta(seconds=3),
        multiplier=2,
        jitter_ratio=0,
    )
    assert policy.delay_seconds(1, random_value=0.5) == 1
    assert policy.delay_seconds(3, random_value=0.5) == 3
    with pytest.raises(DomainValidationError):
        ProviderRetryPolicy(max_attempts=0)


def test_transient_failures_are_retried(fixed_instant) -> None:
    sleeps = []
    provider = StubProvider(
        fixed_instant,
        failures=2,
        retry_policy=ProviderRetryPolicy(
            max_attempts=3,
            initial_delay=timedelta(milliseconds=1),
            maximum_delay=timedelta(milliseconds=10),
            jitter_ratio=0,
        ),
        sleeper=sleeps.append,
        random_source=lambda: 0.5,
    )

    provider.fetch_price_bars(_request())

    assert provider.calls == 3
    assert sleeps == [0.01, 0.01]


def test_retry_exhaustion_propagates(fixed_instant) -> None:
    provider = StubProvider(
        fixed_instant,
        failures=3,
        retry_policy=ProviderRetryPolicy(max_attempts=2),
        sleeper=lambda _: None,
    )
    with pytest.raises(TransientMarketDataProviderError):
        provider.fetch_price_bars(_request())
    assert provider.calls == 2


def test_foreign_page_cannot_be_decoded(fixed_instant) -> None:
    provider = StubProvider(fixed_instant)
    page = MarketDataPage(
        ProviderName("other"),
        "a" * 64,
        "id",
        fixed_instant,
        "v1",
        "application/json",
        b"{}",
        None,
        0,
    )
    with pytest.raises(ProviderContractError, match="another provider"):
        provider.decode_price_bars(page)


def test_transient_error_rejects_negative_retry_after() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        TransientMarketDataProviderError(
            "invalid", retry_after=timedelta(seconds=-1)
        )


def test_sliding_window_rate_limiter_waits() -> None:
    now = [0.0]
    sleeps = []

    def monotonic():
        return now[0]

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = SlidingWindowRateLimiter(2, timedelta(seconds=1), monotonic=monotonic, sleeper=sleep)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert sleeps == [1.0]
