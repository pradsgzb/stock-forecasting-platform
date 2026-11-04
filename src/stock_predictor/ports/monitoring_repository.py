"""Port for append-only monitoring evidence and alerts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import ModelVersionId
from stock_predictor.domain.mlops.monitoring import (
    DriftReport,
    MonitoringAlert,
    PerformanceSnapshot,
)


@runtime_checkable
class MonitoringRepository(Protocol):
    def append_drift_report(self, report: DriftReport) -> None:
        ...

    def append_performance_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        ...

    def append_alert(self, alert: MonitoringAlert) -> None:
        ...

    def drift_reports(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[DriftReport, ...]:
        ...

    def performance_snapshots(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[PerformanceSnapshot, ...]:
        ...

    def alerts(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[MonitoringAlert, ...]:
        ...
