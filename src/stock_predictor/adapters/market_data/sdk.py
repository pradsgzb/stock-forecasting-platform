"""Reusable resilience, rate-limiting, and contract enforcement for provider adapters."""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock
from typing import Protocol

from stock_predictor.domain.common.errors import DomainValidationError, ProviderContractError
from stock_predictor.domain.market_data.contracts import (
    MarketDataPage,
    PriceBarRequest,
    ProviderCapabilities,
    ProviderPriceBar,
)
from stock_predictor.ports.market_data_provider import TransientMarketDataProviderError


class RateLimiter(Protocol):
    """Synchronous provider-call admission control."""

    def acquire(self) -> None:
        ...


class NoOpRateLimiter:
    """Explicit no-op limiter for providers without client-side call limits."""

    def acquire(self) -> None:
        return None


class SlidingWindowRateLimiter:
    """Thread-safe rolling-window limiter using monotonic time.

    Distributed deployments should replace this adapter with a shared limiter while preserving
    the same provider SDK contract.
    """

    __slots__ = ("_calls", "_lock", "_max_calls", "_monotonic", "_period", "_sleep")

    def __init__(
        self,
        max_calls: int,
        period: timedelta,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_calls <= 0 or period <= timedelta():
            raise DomainValidationError("Rate-limit capacity and period must be positive")
        self._max_calls = max_calls
        self._period = period.total_seconds()
        self._monotonic = monotonic
        self._sleep = sleeper
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._monotonic()
                boundary = now - self._period
                while self._calls and self._calls[0] <= boundary:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                wait_seconds = max(0.0, self._period - (now - self._calls[0]))
            self._sleep(wait_seconds)


@dataclass(frozen=True, slots=True)
class ProviderRetryPolicy:
    """Bounded exponential backoff with optional proportional jitter."""

    max_attempts: int = 3
    initial_delay: timedelta = timedelta(milliseconds=250)
    maximum_delay: timedelta = timedelta(seconds=5)
    multiplier: float = 2.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise DomainValidationError("Retry max_attempts must be positive")
        if self.initial_delay < timedelta() or self.maximum_delay < self.initial_delay:
            raise DomainValidationError("Retry delays are invalid")
        if self.multiplier < 1 or not 0 <= self.jitter_ratio <= 1:
            raise DomainValidationError("Retry multiplier or jitter ratio is invalid")

    def delay_seconds(self, failed_attempt: int, *, random_value: float) -> float:
        """Return a bounded delay after the numbered failed attempt (starting at one)."""
        if failed_attempt <= 0 or not 0 <= random_value <= 1:
            raise DomainValidationError("Retry attempt and random value are invalid")
        base = min(
            self.maximum_delay.total_seconds(),
            self.initial_delay.total_seconds() * self.multiplier ** (failed_attempt - 1),
        )
        jitter = base * self.jitter_ratio * ((2 * random_value) - 1)
        return max(0.0, base + jitter)


class ResilientMarketDataProvider(ABC):
    """Template method for provider adapters with consistent safeguards."""

    __slots__ = ("_capabilities", "_random", "_rate_limiter", "_retry", "_sleep")

    def __init__(
        self,
        capabilities: ProviderCapabilities,
        *,
        retry_policy: ProviderRetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._capabilities = capabilities
        self._retry = retry_policy or ProviderRetryPolicy()
        self._rate_limiter = rate_limiter or NoOpRateLimiter()
        self._sleep = sleeper
        self._random = random_source

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def fetch_price_bars(
        self, request: PriceBarRequest, *, cursor: str | None = None
    ) -> MarketDataPage:
        self._capabilities.validate(request)
        for attempt in range(1, self._retry.max_attempts + 1):
            self._rate_limiter.acquire()
            try:
                page = self._fetch_price_bars(request, cursor=cursor)
                self._validate_page_contract(request, page)
                return page
            except TransientMarketDataProviderError as exc:
                if attempt >= self._retry.max_attempts:
                    raise
                policy_delay = self._retry.delay_seconds(
                    attempt, random_value=self._random()
                )
                provider_delay = 0.0 if exc.retry_after is None else exc.retry_after.total_seconds()
                self._sleep(max(policy_delay, provider_delay))
        raise AssertionError("Unreachable retry loop")

    def decode_price_bars(self, page: MarketDataPage) -> tuple[ProviderPriceBar, ...]:
        if page.provider != self._capabilities.descriptor.name:
            raise ProviderContractError("Provider cannot decode a page owned by another provider")
        return self._decode_price_bars(page)

    def _validate_page_contract(
        self, request: PriceBarRequest, page: MarketDataPage
    ) -> None:
        if page.provider != self._capabilities.descriptor.name:
            raise ProviderContractError("Provider page identity does not match adapter")
        if page.request_fingerprint != request.request_fingerprint:
            raise ProviderContractError("Provider page does not match the request fingerprint")
        if page.next_cursor is not None and not self._capabilities.supports_pagination:
            raise ProviderContractError("Provider returned a cursor but declared no pagination")

    @abstractmethod
    def _fetch_price_bars(
        self, request: PriceBarRequest, *, cursor: str | None
    ) -> MarketDataPage:
        raise NotImplementedError

    @abstractmethod
    def _decode_price_bars(
        self, page: MarketDataPage
    ) -> tuple[ProviderPriceBar, ...]:
        raise NotImplementedError
