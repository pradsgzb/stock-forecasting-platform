from datetime import UTC, date, datetime

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import (
    EffectivePeriod,
    InformationTimeline,
    UtcInstant,
)


def test_utc_instant_rejects_naive_datetime() -> None:
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        UtcInstant(datetime(2026, 1, 1, 12, 0))


def test_utc_instant_normalizes_offset() -> None:
    instant = UtcInstant.parse("2026-01-01T17:30:00+05:30")
    assert instant.value == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert instant.isoformat() == "2026-01-01T12:00:00Z"


def test_adjacent_effective_periods_do_not_overlap() -> None:
    old = EffectivePeriod(date(2020, 1, 1), date(2025, 1, 1))
    new = EffectivePeriod(date(2025, 1, 1))

    assert not old.overlaps(new)
    assert not old.contains(date(2025, 1, 1))
    assert new.contains(date(2025, 1, 1))


def test_information_timeline_requires_monotonic_availability() -> None:
    event = UtcInstant.parse("2026-01-01T10:00:00Z")
    published = UtcInstant.parse("2026-01-01T10:01:00Z")
    received = UtcInstant.parse("2026-01-01T10:02:00Z")
    processed = UtcInstant.parse("2026-01-01T10:03:00Z")

    timeline = InformationTimeline(event, published, received, processed)
    assert timeline.available_by(processed)

    with pytest.raises(DomainValidationError, match="event <= publication"):
        InformationTimeline(published, event, received, processed)


def test_utc_instant_accepts_lowercase_z_only_as_suffix() -> None:
    instant = UtcInstant.parse("2026-01-01T12:00:00z")
    assert instant.value == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_utc_instant_does_not_rewrite_embedded_z() -> None:
    with pytest.raises(DomainValidationError, match="Invalid ISO-8601 instant"):
        UtcInstant.parse("2026-Z1-01T12:00:00+00:00")
