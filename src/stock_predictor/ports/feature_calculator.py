"""Extension contract for versioned feature calculators."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.market_data.features import (
    FeatureDefinition,
    FeatureInputBar,
    FeatureObservation,
)


@runtime_checkable
class FeatureCalculator(Protocol):
    @property
    def definition(self) -> FeatureDefinition:
        ...

    def calculate(
        self, history: tuple[FeatureInputBar, ...]
    ) -> FeatureObservation:
        ...
