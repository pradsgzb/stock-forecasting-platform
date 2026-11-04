"""Registry for versioned feature-calculator strategies."""

from __future__ import annotations

from stock_predictor.domain.common.errors import DomainConflictError, DomainNotFoundError
from stock_predictor.ports.feature_calculator import FeatureCalculator


class FeatureCalculatorRegistry:
    __slots__ = ("_calculators",)

    def __init__(self, calculators: tuple[FeatureCalculator, ...] = ()) -> None:
        self._calculators: dict[str, FeatureCalculator] = {}
        for calculator in calculators:
            self.register(calculator)

    def register(self, calculator: FeatureCalculator) -> None:
        key = calculator.definition.key
        if key in self._calculators:
            raise DomainConflictError(f"Feature calculator already registered: {key}")
        self._calculators[key] = calculator

    def get(self, key: str) -> FeatureCalculator:
        try:
            return self._calculators[key]
        except KeyError as exc:
            raise DomainNotFoundError(f"Feature calculator is not registered: {key}") from exc

    def all(self) -> tuple[FeatureCalculator, ...]:
        return tuple(self._calculators[key] for key in sorted(self._calculators))
