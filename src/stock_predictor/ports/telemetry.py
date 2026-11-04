"""Low-cardinality operational telemetry port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.operations.slo import HealthState


@runtime_checkable
class Telemetry(Protocol):
    def observe_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        ...

    def record_paper_order(self, *, side: str, outcome: str) -> None:
        ...

    def set_component_health(self, *, component: str, state: HealthState) -> None:
        ...

    def render(self) -> bytes:
        ...

    @property
    def content_type(self) -> str:
        ...
