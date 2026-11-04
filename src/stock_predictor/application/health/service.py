"""Liveness and readiness checks without exposing infrastructure exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.operations.slo import HealthCheckResult, HealthState
from stock_predictor.ports.operational_store import OperationalUnitOfWorkFactory
from stock_predictor.ports.telemetry import Telemetry


@dataclass(frozen=True, slots=True)
class HealthReport:
    state: HealthState
    checks: tuple[HealthCheckResult, ...]


class HealthService:
    def __init__(
        self,
        store: OperationalUnitOfWorkFactory,
        clock: Clock,
        telemetry: Telemetry,
    ) -> None:
        self._store = store
        self._clock = clock
        self._telemetry = telemetry

    def liveness(self) -> HealthReport:
        result = HealthCheckResult(
            "application",
            HealthState.HEALTHY,
            self._clock.now(),
            "Process event loop is responsive",
            Decimal(0),
        )
        self._telemetry.set_component_health(
            component=result.component,
            state=result.state,
        )
        return HealthReport(HealthState.HEALTHY, (result,))

    def readiness(self) -> HealthReport:
        started = perf_counter()
        healthy = self._store.health_check()
        elapsed_ms = Decimal(str((perf_counter() - started) * 1000))
        database = HealthCheckResult(
            "operational_database",
            HealthState.HEALTHY if healthy else HealthState.UNHEALTHY,
            self._clock.now(),
            "Operational database accepted a validation query"
            if healthy
            else "Operational database validation query failed",
            elapsed_ms,
        )
        self._telemetry.set_component_health(
            component=database.component,
            state=database.state,
        )
        return HealthReport(database.state, (database,))
