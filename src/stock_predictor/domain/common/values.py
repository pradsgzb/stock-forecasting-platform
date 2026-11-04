"""Validated scalar financial value objects."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TypeAlias

from stock_predictor.domain.common.errors import DomainValidationError

DecimalInput: TypeAlias = Decimal | int | str


def to_decimal(value: DecimalInput, *, field_name: str) -> Decimal:
    """Convert a safe input to a finite Decimal.

    Floats are deliberately excluded because their binary representation can silently alter
    financial values before Decimal receives them.
    """
    if isinstance(value, bool) or isinstance(value, float):
        msg = f"{field_name} must not be created from bool or float"
        raise DomainValidationError(msg)
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        msg = f"Invalid decimal value for {field_name}: {value!r}"
        raise DomainValidationError(msg) from exc
    if not decimal_value.is_finite():
        msg = f"{field_name} must be finite"
        raise DomainValidationError(msg)
    return decimal_value


@dataclass(frozen=True, slots=True, order=True)
class Probability:
    """Probability in the inclusive interval `[0, 1]`."""

    value: Decimal

    def __init__(self, value: DecimalInput) -> None:
        normalized = to_decimal(value, field_name="probability")
        if not Decimal(0) <= normalized <= Decimal(1):
            msg = "Probability must be between 0 and 1 inclusive"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True, order=True)
class Quantity:
    """Non-negative exact quantity."""

    value: Decimal

    def __init__(self, value: DecimalInput) -> None:
        normalized = to_decimal(value, field_name="quantity")
        if normalized < 0:
            msg = "Quantity cannot be negative"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True, order=True)
class SimpleReturn:
    """Simple return as a fraction, with a lower bound of -1."""

    value: Decimal

    def __init__(self, value: DecimalInput) -> None:
        normalized = to_decimal(value, field_name="simple return")
        if normalized < Decimal(-1):
            msg = "Simple return cannot be below -1"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True, order=True)
class LogReturn:
    """Finite logarithmic return."""

    value: Decimal

    def __init__(self, value: DecimalInput) -> None:
        object.__setattr__(self, "value", to_decimal(value, field_name="log return"))


@dataclass(frozen=True, slots=True, order=True)
class Percentage:
    """Percentage value stored in percentage points, e.g. `12.5` means 12.5%."""

    value: Decimal

    def __init__(self, value: DecimalInput) -> None:
        object.__setattr__(self, "value", to_decimal(value, field_name="percentage"))

    def as_fraction(self) -> Decimal:
        """Return the percentage as a fractional rate."""
        return self.value / Decimal(100)
