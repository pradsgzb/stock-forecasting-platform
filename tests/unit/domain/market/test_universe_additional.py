from datetime import date

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import InstrumentId, UniverseSnapshotId
from stock_predictor.domain.market.universe import UniverseSnapshot


def test_universe_validates_required_fields_and_contains(fixed_instant) -> None:
    instrument_id = InstrumentId.new()
    snapshot = UniverseSnapshot(
        UniverseSnapshotId.new(),
        "Universe",
        date(2026, 1, 2),
        frozenset({instrument_id}),
        "v1",
        fixed_instant,
    )
    assert snapshot.contains(instrument_id)

    with pytest.raises(DomainValidationError, match="cannot be empty"):
        UniverseSnapshot(
            UniverseSnapshotId.new(),
            "Universe",
            date(2026, 1, 2),
            frozenset(),
            "v1",
            fixed_instant,
        )
    with pytest.raises(DomainValidationError, match="name"):
        UniverseSnapshot(
            UniverseSnapshotId.new(),
            " ",
            date(2026, 1, 2),
            frozenset({instrument_id}),
            "v1",
            fixed_instant,
        )
