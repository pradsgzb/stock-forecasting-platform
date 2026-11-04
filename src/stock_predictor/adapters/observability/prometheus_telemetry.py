"""Low-cardinality Prometheus telemetry implementation."""

from __future__ import annotations

import re

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import generate_latest

from stock_predictor.domain.operations.slo import HealthState

_ROUTE = re.compile(r"^/[A-Za-z0-9_{}./:-]{0,199}$")
_COMPONENT = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


class PrometheusTelemetry:
    def __init__(self, *, namespace: str = "stock_predictor") -> None:
        self._registry = CollectorRegistry(auto_describe=True)
        self._requests = Counter(
            "http_requests_total",
            "Completed HTTP requests.",
            ("method", "route", "status_class"),
            namespace=namespace,
            registry=self._registry,
        )
        self._duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration by route template.",
            ("method", "route"),
            namespace=namespace,
            registry=self._registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
        )
        self._paper_orders = Counter(
            "paper_orders_total",
            "Paper-only order outcomes.",
            ("side", "outcome"),
            namespace=namespace,
            registry=self._registry,
        )
        self._health = Gauge(
            "component_health",
            "Component health: 1 healthy, 0.5 degraded, 0 unhealthy.",
            ("component",),
            namespace=namespace,
            registry=self._registry,
        )

    def observe_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        method_name = method.strip().upper()
        route_name = route.strip()
        if method_name not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
            raise ValueError("Unsupported HTTP method label")
        if not _ROUTE.fullmatch(route_name):
            route_name = "/unmatched"
        if not 100 <= status_code <= 599 or duration_seconds < 0:
            raise ValueError("HTTP telemetry values are invalid")
        status_class = f"{status_code // 100}xx"
        self._requests.labels(method_name, route_name, status_class).inc()
        self._duration.labels(method_name, route_name).observe(duration_seconds)

    def record_paper_order(self, *, side: str, outcome: str) -> None:
        side_name = side.strip().lower()
        outcome_name = outcome.strip().lower()
        if side_name not in {"buy", "sell"}:
            raise ValueError("Paper-order side label is invalid")
        if outcome_name not in {"filled", "replayed", "rejected"}:
            raise ValueError("Paper-order outcome label is invalid")
        self._paper_orders.labels(side_name, outcome_name).inc()

    def set_component_health(self, *, component: str, state: HealthState) -> None:
        name = component.strip().lower()
        if not _COMPONENT.fullmatch(name):
            raise ValueError("Health component label is invalid")
        value = {
            HealthState.HEALTHY: 1.0,
            HealthState.DEGRADED: 0.5,
            HealthState.UNHEALTHY: 0.0,
        }[state]
        self._health.labels(name).set(value)

    def render(self) -> bytes:
        return generate_latest(self._registry)

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST


class NoopTelemetry:
    """Safe default when an operational metrics backend is intentionally absent."""

    def observe_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        del method, route, status_code, duration_seconds

    def record_paper_order(self, *, side: str, outcome: str) -> None:
        del side, outcome

    def set_component_health(self, *, component: str, state: HealthState) -> None:
        del component, state

    def render(self) -> bytes:
        return b""

    @property
    def content_type(self) -> str:
        return "text/plain; charset=utf-8"
