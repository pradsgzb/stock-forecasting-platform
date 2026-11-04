from stock_predictor.adapters.observability.prometheus_telemetry import NoopTelemetry
from stock_predictor.application.health.service import HealthService
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.operations.slo import HealthState


class UnhealthyStore:
    def health_check(self) -> bool:
        return False


def test_liveness_and_readiness_report_component_state(
    operational_store,
    fixed_instant,
) -> None:
    service = HealthService(
        operational_store,
        FixedClock(fixed_instant),
        NoopTelemetry(),
    )

    assert service.liveness().state is HealthState.HEALTHY
    ready = service.readiness()
    assert ready.state is HealthState.HEALTHY
    assert ready.checks[0].component == "operational_database"


def test_failed_database_check_reports_unhealthy_without_exception(fixed_instant) -> None:
    service = HealthService(
        UnhealthyStore(),
        FixedClock(fixed_instant),
        NoopTelemetry(),
    )

    report = service.readiness()

    assert report.state is HealthState.UNHEALTHY
    assert "failed" in report.checks[0].detail.lower()
