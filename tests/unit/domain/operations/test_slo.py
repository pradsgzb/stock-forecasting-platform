from datetime import timedelta
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import SloSnapshotId
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.operations.slo import (
    HealthState,
    ServiceLevelObjective,
    SloIndicator,
    SloSnapshot,
)


def test_slo_objective_and_snapshot_fingerprint(fixed_instant) -> None:
    objective = ServiceLevelObjective(
        "api.availability",
        SloIndicator.AVAILABILITY,
        "0.999",
        3600,
    )
    window = InstantInterval(
        fixed_instant,
        fixed_instant.plus(timedelta(minutes=30)),
    )
    snapshot = SloSnapshot(
        SloSnapshotId.new(),
        objective,
        window,
        1000,
        999,
        Decimal("0.999"),
        Decimal("0"),
        HealthState.HEALTHY,
        fixed_instant.plus(timedelta(hours=1)),
    )

    assert len(snapshot.fingerprint) == 64


def test_latency_slo_requires_threshold() -> None:
    with pytest.raises(DomainValidationError, match="latency threshold"):
        ServiceLevelObjective("api.latency", SloIndicator.LATENCY, "0.95", 60)
    with pytest.raises(DomainValidationError, match="Only latency"):
        ServiceLevelObjective(
            "api.availability",
            SloIndicator.AVAILABILITY,
            "0.99",
            60,
            "100",
        )
