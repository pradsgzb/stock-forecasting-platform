from datetime import timedelta

import pytest

from stock_predictor.application.observability.slo import SloEvaluationService
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import ObservabilityError
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.operations.slo import (
    HealthState,
    ServiceLevelObjective,
    SloIndicator,
)


def test_slo_evaluation_persists_healthy_degraded_and_unhealthy_snapshots(
    operational_store,
    fixed_instant,
) -> None:
    service = SloEvaluationService(operational_store, FixedClock(fixed_instant))
    objective = ServiceLevelObjective(
        "api.availability",
        SloIndicator.AVAILABILITY,
        "0.99",
        3600,
    )
    window = InstantInterval(
        fixed_instant.plus(timedelta(hours=-1)),
        fixed_instant,
    )

    healthy = service.evaluate(objective, window, total_events=100, good_events=99)
    degraded = service.evaluate(objective, window, total_events=100, good_events=98)
    unhealthy = service.evaluate(objective, window, total_events=100, good_events=90)

    assert healthy.state is HealthState.HEALTHY
    assert degraded.state is HealthState.DEGRADED
    assert unhealthy.state is HealthState.UNHEALTHY
    assert service.latest("api.availability") == unhealthy


def test_slo_evaluation_rejects_invalid_counts(operational_store, fixed_instant) -> None:
    service = SloEvaluationService(operational_store, FixedClock(fixed_instant))
    objective = ServiceLevelObjective(
        "api.availability",
        SloIndicator.AVAILABILITY,
        "0.99",
        3600,
    )
    window = InstantInterval(
        fixed_instant.plus(timedelta(hours=-1)),
        fixed_instant,
    )
    with pytest.raises(ObservabilityError):
        service.evaluate(objective, window, total_events=0, good_events=0)
