import pytest

from stock_predictor.adapters.observability.prometheus_telemetry import (
    NoopTelemetry,
    PrometheusTelemetry,
)
from stock_predictor.domain.operations.slo import HealthState


def test_prometheus_telemetry_uses_bounded_labels_and_renders_metrics() -> None:
    telemetry = PrometheusTelemetry(namespace="test_stock")
    telemetry.observe_http_request(
        method="GET",
        route="/api/v1/paper/accounts/{account_id}",
        status_code=200,
        duration_seconds=0.025,
    )
    telemetry.observe_http_request(
        method="GET",
        route="/api/v1/accounts/actual-sensitive-id?token=secret",
        status_code=404,
        duration_seconds=0,
    )
    telemetry.record_paper_order(side="buy", outcome="filled")
    telemetry.set_component_health(component="operational_database", state=HealthState.HEALTHY)

    rendered = telemetry.render().decode()
    assert 'route="/api/v1/paper/accounts/{account_id}"' in rendered
    assert 'route="/unmatched"' in rendered
    assert "actual-sensitive-id" not in rendered
    assert "test_stock_paper_orders_total" in rendered
    assert telemetry.content_type.startswith("text/plain")


@pytest.mark.parametrize(
    ("method", "route", "status", "duration"),
    [
        ("TRACE", "/", 200, 0),
        ("GET", "/", 99, 0),
        ("GET", "/", 200, -1),
    ],
)
def test_http_metric_validation(method, route, status, duration) -> None:
    telemetry = PrometheusTelemetry(namespace="validation")
    with pytest.raises(ValueError):
        telemetry.observe_http_request(
            method=method,
            route=route,
            status_code=status,
            duration_seconds=duration,
        )


@pytest.mark.parametrize(
    ("side", "outcome"),
    [("hold", "filled"), ("buy", "unknown")],
)
def test_paper_order_metric_validation(side: str, outcome: str) -> None:
    with pytest.raises(ValueError):
        PrometheusTelemetry(namespace="validation").record_paper_order(
            side=side,
            outcome=outcome,
        )


def test_health_metric_validation() -> None:
    with pytest.raises(ValueError):
        PrometheusTelemetry(namespace="validation").set_component_health(
            component="Invalid Component!",
            state=HealthState.UNHEALTHY,
        )


def test_noop_telemetry_accepts_all_protocol_calls() -> None:
    telemetry = NoopTelemetry()
    telemetry.observe_http_request(
        method="GET", route="/", status_code=200, duration_seconds=0
    )
    telemetry.record_paper_order(side="buy", outcome="filled")
    telemetry.set_component_health(component="application", state=HealthState.HEALTHY)
    assert telemetry.render() == b""
    assert telemetry.content_type == "text/plain; charset=utf-8"
