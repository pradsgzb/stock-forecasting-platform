"""Service-level objective evaluation and immutable persistence."""

from __future__ import annotations

from decimal import Decimal

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import ObservabilityError
from stock_predictor.domain.common.identifiers import SloSnapshotId
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.operations.slo import (
    HealthState,
    ServiceLevelObjective,
    SloSnapshot,
)
from stock_predictor.ports.operational_store import OperationalUnitOfWorkFactory


class SloEvaluationService:
    def __init__(self, store: OperationalUnitOfWorkFactory, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def evaluate(
        self,
        objective: ServiceLevelObjective,
        window: InstantInterval,
        *,
        total_events: int,
        good_events: int,
    ) -> SloSnapshot:
        if total_events <= 0 or not 0 <= good_events <= total_events:
            raise ObservabilityError("SLO event counts are invalid")
        measured = Decimal(good_events) / Decimal(total_events)
        allowed_bad_fraction = Decimal(1) - objective.target
        actual_bad_fraction = Decimal(total_events - good_events) / Decimal(total_events)
        remaining = allowed_bad_fraction - actual_bad_fraction
        if measured >= objective.target:
            state = HealthState.HEALTHY
        elif measured >= objective.target * Decimal("0.98"):
            state = HealthState.DEGRADED
        else:
            state = HealthState.UNHEALTHY
        snapshot = SloSnapshot(
            snapshot_id=SloSnapshotId.new(),
            objective=objective,
            window=window,
            total_events=total_events,
            good_events=good_events,
            measured_value=measured,
            error_budget_remaining=max(Decimal(-1), min(Decimal(1), remaining)),
            state=state,
            created_at=self._clock.now(),
        )
        with self._store() as uow:
            uow.slos.append(snapshot)
            uow.commit()
        return snapshot

    def latest(self, objective_name: str) -> SloSnapshot | None:
        with self._store() as uow:
            return uow.slos.latest(objective_name)
