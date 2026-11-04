"""Explicit provider registry owned by the application layer."""

from __future__ import annotations

from stock_predictor.domain.common.errors import DomainConflictError, DomainNotFoundError
from stock_predictor.domain.market.identifiers import ProviderName
from stock_predictor.ports.market_data_provider import MarketDataProvider


class MarketDataProviderRegistry:
    """Resolves provider adapters without a global service locator."""

    __slots__ = ("_providers",)

    def __init__(self, providers: tuple[MarketDataProvider, ...] = ()) -> None:
        self._providers: dict[ProviderName, MarketDataProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: MarketDataProvider) -> None:
        name = provider.capabilities.descriptor.name
        if name in self._providers:
            raise DomainConflictError(f"Market-data provider is already registered: {name}")
        self._providers[name] = provider

    def get(self, name: ProviderName) -> MarketDataProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise DomainNotFoundError(f"Market-data provider is not registered: {name}") from exc

    def all(self) -> tuple[MarketDataProvider, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers, key=str))
