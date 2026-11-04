from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stock_predictor.domain.common.clock import FixedClock, SystemClock
from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.money import Currency, Money
from stock_predictor.domain.common.temporal import (
    EffectivePeriod,
    HorizonUnit,
    InstantInterval,
    PredictionHorizon,
    UtcInstant,
)
from stock_predictor.domain.common.values import LogReturn, Quantity


def test_money_subtraction_multiplication_and_zero() -> None:
    usd = Currency("USD")
    assert Money(10, usd) - Money(4, usd) == Money(6, usd)
    assert Money(10, usd).multiply("1.5") == Money(15, usd)
    assert Money.zero(usd).amount == Decimal(0)


def test_invalid_decimal_and_currency_are_rejected() -> None:
    with pytest.raises(DomainValidationError):
        LogReturn("NaN")
    with pytest.raises(DomainValidationError):
        Quantity(True)  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        Currency("US")


def test_temporal_validation_and_helpers() -> None:
    start = UtcInstant(datetime(2026, 1, 1, tzinfo=UTC))
    end = start.plus(timedelta(hours=1))
    interval = InstantInterval(start, end)

    assert interval.contains(start)
    overlapping = InstantInterval(
        end.plus(timedelta(minutes=-1)),
        end.plus(timedelta(1)),
    )
    assert interval.overlaps(overlapping)
    with pytest.raises(DomainValidationError):
        InstantInterval(end, start)
    with pytest.raises(DomainValidationError):
        EffectivePeriod(date(2026, 1, 2), date(2026, 1, 2))
    with pytest.raises(DomainValidationError):
        UtcInstant.parse("invalid")


def test_prediction_horizon_and_clocks() -> None:
    with pytest.raises(DomainValidationError):
        PredictionHorizon(0, HorizonUnit.TRADING_SESSIONS)
    fixed = UtcInstant(datetime(2026, 1, 1, tzinfo=UTC))
    assert FixedClock(fixed).now() == fixed
    assert SystemClock().now().value.tzinfo is UTC
