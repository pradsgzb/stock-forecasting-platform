from dataclasses import replace
from datetime import date

import pytest

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainValidationError,
    OverlappingEffectivePeriodError,
)
from stock_predictor.domain.common.temporal import EffectivePeriod
from stock_predictor.domain.market.identifiers import (
    InstrumentIdentifier,
    InstrumentIdentifierScheme,
)


def test_listing_interval(sample_instrument) -> None:
    assert not sample_instrument.is_listed_on(date(2019, 12, 31))
    assert sample_instrument.is_listed_on(date(2020, 1, 2))
    delisted = replace(sample_instrument, delisting_date=date(2025, 1, 1))
    assert not delisted.is_listed_on(date(2025, 1, 1))


def test_invalid_delisting_date_and_blank_name(sample_instrument) -> None:
    with pytest.raises(DomainValidationError, match="later than listing"):
        replace(sample_instrument, delisting_date=sample_instrument.listing_date)
    with pytest.raises(DomainValidationError, match="display name"):
        replace(sample_instrument, display_name="   ")


def test_identifier_history_rejects_overlap(sample_instrument) -> None:
    first = InstrumentIdentifier(
        InstrumentIdentifierScheme.ISIN,
        "US0000000001",
        EffectivePeriod(date(2020, 1, 1), date(2025, 1, 1)),
    )
    overlap = InstrumentIdentifier(
        InstrumentIdentifierScheme.ISIN,
        "US0000000002",
        EffectivePeriod(date(2024, 1, 1)),
    )

    with pytest.raises(OverlappingEffectivePeriodError):
        sample_instrument.with_identifier(first).with_identifier(overlap)


def test_duplicate_identifier_is_rejected(sample_instrument) -> None:
    identifier = InstrumentIdentifier(
        InstrumentIdentifierScheme.ISIN,
        "US0000000001",
        EffectivePeriod(date(2020, 1, 1)),
    )
    instrument = sample_instrument.with_identifier(identifier)

    with pytest.raises(DomainConflictError, match="already exists"):
        instrument.with_identifier(identifier)
