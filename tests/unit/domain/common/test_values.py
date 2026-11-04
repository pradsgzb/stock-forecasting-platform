from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.values import Percentage, Probability, Quantity, SimpleReturn


def test_probability_bounds() -> None:
    assert Probability("0.75").value == Decimal("0.75")
    with pytest.raises(DomainValidationError):
        Probability("1.01")


def test_quantity_cannot_be_negative() -> None:
    with pytest.raises(DomainValidationError):
        Quantity(-1)


def test_simple_return_lower_bound() -> None:
    assert SimpleReturn("-1").value == Decimal("-1")
    with pytest.raises(DomainValidationError):
        SimpleReturn("-1.0001")


def test_percentage_converts_to_fraction() -> None:
    assert Percentage("12.5").as_fraction() == Decimal("0.125")
