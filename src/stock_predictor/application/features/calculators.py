"""Reference feature calculators implemented with exact decimal arithmetic."""

from __future__ import annotations

from decimal import Decimal, localcontext

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.market_data.features import (
    FeatureDefinition,
    FeatureInputBar,
    FeatureObservation,
)


def _missing(
    definition: FeatureDefinition,
    history: tuple[FeatureInputBar, ...],
    reason: str,
) -> FeatureObservation:
    return FeatureObservation(
        definition=definition,
        value=None,
        missing_reason=reason,
        source_bar_ids=tuple(item.bar_id for item in history),
    )


class ClosePriceCalculator:
    __slots__ = ("_definition",)

    def __init__(self, *, version: str = "1.0.0") -> None:
        self._definition = FeatureDefinition(
            name="close_price",
            version=version,
            description="Latest point-in-time adjusted closing price.",
            lookback_sessions=0,
            minimum_history=1,
        )

    @property
    def definition(self) -> FeatureDefinition:
        return self._definition

    def calculate(
        self, history: tuple[FeatureInputBar, ...]
    ) -> FeatureObservation:
        if not history:
            return _missing(self.definition, history, "no price history")
        latest = history[-1]
        return FeatureObservation(
            self.definition, latest.close_price, None, (latest.bar_id,)
        )


class SimpleReturnCalculator:
    __slots__ = ("_definition", "_periods")

    def __init__(self, periods: int, *, version: str = "1.0.0") -> None:
        if periods <= 0:
            raise DomainValidationError("Return periods must be positive")
        self._periods = periods
        self._definition = FeatureDefinition(
            name=f"simple_return_{periods}s",
            version=version,
            description=f"Simple close-to-close return over {periods} trading sessions.",
            lookback_sessions=periods,
            minimum_history=periods + 1,
        )

    @property
    def definition(self) -> FeatureDefinition:
        return self._definition

    def calculate(
        self, history: tuple[FeatureInputBar, ...]
    ) -> FeatureObservation:
        required = self._periods + 1
        relevant = history[-required:]
        if len(relevant) < required:
            return _missing(self.definition, relevant, "insufficient price history")
        start = relevant[0].close_price
        value = (relevant[-1].close_price / start) - Decimal(1)
        return FeatureObservation(
            self.definition, value, None, tuple(item.bar_id for item in relevant)
        )


class SimpleMovingAverageCalculator:
    __slots__ = ("_definition", "_window")

    def __init__(self, window: int, *, version: str = "1.0.0") -> None:
        if window <= 0:
            raise DomainValidationError("Moving-average window must be positive")
        self._window = window
        self._definition = FeatureDefinition(
            name=f"sma_{window}s",
            version=version,
            description=f"Simple moving average of adjusted close over {window} sessions.",
            lookback_sessions=window - 1,
            minimum_history=window,
        )

    @property
    def definition(self) -> FeatureDefinition:
        return self._definition

    def calculate(
        self, history: tuple[FeatureInputBar, ...]
    ) -> FeatureObservation:
        relevant = history[-self._window :]
        if len(relevant) < self._window:
            return _missing(self.definition, relevant, "insufficient price history")
        value = sum((item.close_price for item in relevant), start=Decimal(0)) / Decimal(
            self._window
        )
        return FeatureObservation(
            self.definition, value, None, tuple(item.bar_id for item in relevant)
        )


class RollingVolatilityCalculator:
    __slots__ = ("_definition", "_window")

    def __init__(self, window: int, *, version: str = "1.0.0") -> None:
        if window < 2:
            raise DomainValidationError("Volatility window must be at least two returns")
        self._window = window
        self._definition = FeatureDefinition(
            name=f"realized_volatility_{window}s",
            version=version,
            description=f"Sample standard deviation of {window} simple session returns.",
            lookback_sessions=window,
            minimum_history=window + 1,
        )

    @property
    def definition(self) -> FeatureDefinition:
        return self._definition

    def calculate(
        self, history: tuple[FeatureInputBar, ...]
    ) -> FeatureObservation:
        relevant = history[-(self._window + 1) :]
        if len(relevant) < self._window + 1:
            return _missing(self.definition, relevant, "insufficient price history")
        returns = tuple(
            (current.close_price / previous.close_price) - Decimal(1)
            for previous, current in zip(relevant, relevant[1:])
        )
        mean = sum(returns, start=Decimal(0)) / Decimal(len(returns))
        variance = sum(
            ((item - mean) ** 2 for item in returns), start=Decimal(0)
        ) / Decimal(len(returns) - 1)
        with localcontext() as context:
            context.prec = 34
            value = variance.sqrt()
        return FeatureObservation(
            self.definition, value, None, tuple(item.bar_id for item in relevant)
        )


class VolumeRatioCalculator:
    __slots__ = ("_definition", "_window")

    def __init__(self, window: int, *, version: str = "1.0.0") -> None:
        if window <= 0:
            raise DomainValidationError("Volume-ratio window must be positive")
        self._window = window
        self._definition = FeatureDefinition(
            name=f"volume_ratio_{window}s",
            version=version,
            description=f"Current volume divided by mean volume of the prior {window} sessions.",
            lookback_sessions=window,
            minimum_history=window + 1,
        )

    @property
    def definition(self) -> FeatureDefinition:
        return self._definition

    def calculate(
        self, history: tuple[FeatureInputBar, ...]
    ) -> FeatureObservation:
        relevant = history[-(self._window + 1) :]
        if len(relevant) < self._window + 1:
            return _missing(self.definition, relevant, "insufficient volume history")
        prior = relevant[:-1]
        mean = sum((item.volume for item in prior), start=Decimal(0)) / Decimal(
            self._window
        )
        if mean == 0:
            return _missing(self.definition, relevant, "prior mean volume is zero")
        value = relevant[-1].volume / mean
        return FeatureObservation(
            self.definition, value, None, tuple(item.bar_id for item in relevant)
        )
