from datetime import date

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.identifiers import (
    CountryCode,
    InstrumentIdentifier,
    InstrumentIdentifierScheme,
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)


@pytest.mark.parametrize(
    ("factory", "value"),
    [
        (MarketIdentifierCode, "ABC"),
        (CountryCode, "USA"),
        (ProviderName, "has space"),
        (TickerSymbol, "bad symbol"),
    ],
)
def test_invalid_market_identifiers_are_rejected(factory, value) -> None:
    with pytest.raises(DomainValidationError):
        factory(value)


def test_market_identifiers_are_normalized() -> None:
    assert str(MarketIdentifierCode(" xnys ")) == "XNYS"
    assert str(CountryCode(" in ")) == "IN"
    assert str(ProviderName(" Vendor.One ")) == "vendor.one"
    assert str(TickerSymbol(" brk.b ")) == "BRK.B"


def test_provider_identifier_requires_provider() -> None:
    with pytest.raises(DomainValidationError, match="requires a provider"):
        InstrumentIdentifier(
            InstrumentIdentifierScheme.PROVIDER,
            "123",
            EffectivePeriod(date(2020, 1, 1)),
        )


def test_identifier_namespace_distinguishes_provider() -> None:
    first = InstrumentIdentifier(
        InstrumentIdentifierScheme.PROVIDER,
        "123",
        EffectivePeriod(date(2020, 1, 1)),
        ProviderName("one"),
    )
    second = InstrumentIdentifier(
        InstrumentIdentifierScheme.PROVIDER,
        "123",
        EffectivePeriod(date(2020, 1, 1)),
        ProviderName("two"),
    )

    assert not first.has_same_namespace(second)


def test_standard_identifier_rejects_provider_namespace() -> None:
    with pytest.raises(DomainValidationError, match="only valid for provider-specific"):
        InstrumentIdentifier(
            InstrumentIdentifierScheme.ISIN,
            "US0378331005",
            EffectivePeriod(date(2020, 1, 1)),
            ProviderName("vendor"),
        )
