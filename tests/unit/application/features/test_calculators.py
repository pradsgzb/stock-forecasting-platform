from datetime import date, timedelta
from decimal import Decimal

import pytest

from stock_predictor.application.features.calculators import (
    ClosePriceCalculator,
    RollingVolatilityCalculator,
    SimpleMovingAverageCalculator,
    SimpleReturnCalculator,
    VolumeRatioCalculator,
)
from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import PriceBarId
from stock_predictor.domain.market_data.features import FeatureInputBar


def _history(fixed_instant, closes=("100", "102", "101"), volumes=("100", "200", "300")):
    result = []
    for index, (close, volume) in enumerate(zip(closes, volumes, strict=True)):
        close_value = Decimal(close)
        result.append(
            FeatureInputBar(
                PriceBarId.new(),
                date(2025, 7, 1) + timedelta(days=index),
                close_value,
                close_value + 1,
                close_value - 1,
                close_value,
                Decimal(volume),
                fixed_instant,
                f"{index + 1:064x}",
            )
        )
    return tuple(result)


def test_close_price_returns_latest_or_missing(fixed_instant) -> None:
    calculator = ClosePriceCalculator()
    history = _history(fixed_instant)
    observation = calculator.calculate(history)

    assert observation.value == Decimal("101")
    assert observation.source_bar_ids == (history[-1].bar_id,)
    missing = calculator.calculate(())
    assert missing.value is None
    assert missing.missing_reason == "no price history"


def test_simple_return_calculates_and_handles_insufficient_history(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="positive"):
        SimpleReturnCalculator(0)
    calculator = SimpleReturnCalculator(2)
    history = _history(fixed_instant)

    assert calculator.calculate(history).value == Decimal("0.01")
    missing = calculator.calculate(history[-2:])
    assert missing.value is None
    assert missing.missing_reason == "insufficient price history"


def test_simple_moving_average_calculates_and_handles_missing(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="positive"):
        SimpleMovingAverageCalculator(0)
    calculator = SimpleMovingAverageCalculator(3)
    history = _history(fixed_instant)

    assert calculator.calculate(history).value == Decimal("101")
    assert calculator.calculate(history[-2:]).value is None


def test_rolling_volatility_calculates_sample_standard_deviation(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="at least two"):
        RollingVolatilityCalculator(1)
    calculator = RollingVolatilityCalculator(2)
    history = _history(fixed_instant)

    observation = calculator.calculate(history)
    assert observation.value is not None
    assert observation.value > 0
    assert len(observation.source_bar_ids) == 3
    assert calculator.calculate(history[-2:]).missing_reason == "insufficient price history"


def test_volume_ratio_calculates_and_handles_zero_or_missing_history(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="positive"):
        VolumeRatioCalculator(0)
    calculator = VolumeRatioCalculator(2)
    history = _history(fixed_instant)
    assert calculator.calculate(history).value == Decimal("2")
    assert calculator.calculate(history[-2:]).missing_reason == "insufficient volume history"

    zero_history = _history(
        fixed_instant,
        closes=("100", "102", "101"),
        volumes=("0", "0", "300"),
    )
    assert calculator.calculate(zero_history).missing_reason == "prior mean volume is zero"
