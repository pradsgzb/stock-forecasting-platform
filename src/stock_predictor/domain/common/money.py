"""Currency, money, and price value objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from decimal import Decimal

from stock_predictor.domain.common.errors import (
    CurrencyMismatchError,
    DomainValidationError,
)
from stock_predictor.domain.common.values import DecimalInput, to_decimal

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True, order=True)
class Currency:
    """ISO-4217-style three-letter currency code.

    The type validates shape but does not embed a mutable global currency registry.
    """

    code: str

    def __post_init__(self) -> None:
        normalized = self.code.strip().upper()
        if not _CURRENCY_PATTERN.fullmatch(normalized):
            msg = f"Invalid currency code: {self.code!r}"
            raise DomainValidationError(msg)
        object.__setattr__(self, "code", normalized)

    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True, slots=True)
class Money:
    """Exact monetary amount in a specific currency."""

    amount: Decimal
    currency: Currency

    def __init__(self, amount: DecimalInput, currency: Currency) -> None:
        object.__setattr__(self, "amount", to_decimal(amount, field_name="money amount"))
        object.__setattr__(self, "currency", currency)

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        return cls(Decimal(0), currency)

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            msg = f"Currency mismatch: {self.currency} != {other.currency}"
            raise CurrencyMismatchError(msg)

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def multiply(self, factor: DecimalInput) -> Money:
        return Money(self.amount * to_decimal(factor, field_name="money factor"), self.currency)


@total_ordering
@dataclass(frozen=True, slots=True)
class Price:
    """Strictly positive exact price in a currency."""

    amount: Decimal
    currency: Currency

    def __init__(self, amount: DecimalInput, currency: Currency) -> None:
        normalized = to_decimal(amount, field_name="price")
        if normalized <= 0:
            msg = "Price must be greater than zero"
            raise DomainValidationError(msg)
        object.__setattr__(self, "amount", normalized)
        object.__setattr__(self, "currency", currency)

    def _assert_same_currency(self, other: Price) -> None:
        if self.currency != other.currency:
            msg = f"Currency mismatch: {self.currency} != {other.currency}"
            raise CurrencyMismatchError(msg)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Price):
            return NotImplemented
        self._assert_same_currency(other)
        return self.amount < other.amount
