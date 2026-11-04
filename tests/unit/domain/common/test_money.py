from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import CurrencyMismatchError, DomainValidationError
from stock_predictor.domain.common.money import Currency, Money, Price


def test_currency_is_normalized() -> None:
    assert Currency(" usd ").code == "USD"


def test_float_input_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="must not be created"):
        Money(1.1, Currency("USD"))  # type: ignore[arg-type]


def test_money_arithmetic_requires_matching_currency() -> None:
    usd = Currency("USD")
    inr = Currency("INR")

    assert Money("10.25", usd) + Money("2.75", usd) == Money("13.00", usd)
    with pytest.raises(CurrencyMismatchError):
        _ = Money(10, usd) + Money(10, inr)


def test_price_is_strictly_positive() -> None:
    with pytest.raises(DomainValidationError, match="greater than zero"):
        Price(Decimal(0), Currency("USD"))


def test_price_comparison_requires_matching_currency() -> None:
    usd = Currency("USD")
    inr = Currency("INR")

    assert Price("10.00", usd) < Price("10.01", usd)
    assert Price("10.01", usd) >= Price("10.00", usd)
    with pytest.raises(CurrencyMismatchError, match="Currency mismatch"):
        _ = Price("10.00", usd) < Price("900.00", inr)
