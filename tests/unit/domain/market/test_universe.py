from datetime import date

from stock_predictor.domain.common.identifiers import InstrumentId, UniverseSnapshotId
from stock_predictor.domain.market.universe import UniverseSnapshot


def test_universe_fingerprint_is_order_independent(fixed_instant) -> None:
    first = InstrumentId.new()
    second = InstrumentId.new()

    left = UniverseSnapshot(
        UniverseSnapshotId.new(),
        "Liquid US Equities",
        date(2026, 1, 2),
        frozenset((first, second)),
        "v1",
        fixed_instant,
    )
    right = UniverseSnapshot(
        UniverseSnapshotId.new(),
        "Liquid US Equities",
        date(2026, 1, 2),
        frozenset((second, first)),
        "v1",
        fixed_instant,
    )

    assert left.fingerprint == right.fingerprint
    assert left.snapshot_id != right.snapshot_id
