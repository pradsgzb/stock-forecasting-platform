"""Thread-safe append-only monitoring evidence repository."""

from __future__ import annotations

from threading import RLock
from typing import Callable, TypeVar

from stock_predictor.domain.common.errors import ImmutableObjectConflictError
from stock_predictor.domain.common.identifiers import (
    DriftReportId,
    ModelVersionId,
    MonitoringAlertId,
    MonitoringSnapshotId,
)
from stock_predictor.domain.mlops.monitoring import (
    DriftReport,
    MonitoringAlert,
    PerformanceSnapshot,
)


KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


class InMemoryMonitoringRepository:
    __slots__ = ("_alerts", "_drift", "_lock", "_performance")

    def __init__(self) -> None:
        self._drift: dict[DriftReportId, DriftReport] = {}
        self._performance: dict[MonitoringSnapshotId, PerformanceSnapshot] = {}
        self._alerts: dict[MonitoringAlertId, MonitoringAlert] = {}
        self._lock = RLock()

    def append_drift_report(self, report: DriftReport) -> None:
        self._append(
            self._drift,
            report.report_id,
            report,
            report.fingerprint,
            lambda item: item.fingerprint,
        )

    def append_performance_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        self._append(
            self._performance,
            snapshot.snapshot_id,
            snapshot,
            snapshot.fingerprint,
            lambda item: item.fingerprint,
        )

    def append_alert(self, alert: MonitoringAlert) -> None:
        payload = (
            str(alert.model_version_id),
            int(alert.severity),
            alert.category,
            alert.title,
            alert.detail,
            alert.evidence_reference,
            alert.raised_at.isoformat(),
        )
        self._append(
            self._alerts,
            alert.alert_id,
            alert,
            repr(payload),
            self._alert_fingerprint,
        )

    @staticmethod
    def _alert_fingerprint(alert: MonitoringAlert) -> str:
        return repr(
            (
                str(alert.model_version_id),
                int(alert.severity),
                alert.category,
                alert.title,
                alert.detail,
                alert.evidence_reference,
                alert.raised_at.isoformat(),
            )
        )

    def _append(
        self,
        store: dict[KeyT, ValueT],
        key: KeyT,
        value: ValueT,
        fingerprint: str,
        fingerprint_of: Callable[[ValueT], str],
    ) -> None:
        with self._lock:
            existing = store.get(key)
            if existing is None:
                store[key] = value
                return
            if fingerprint_of(existing) != fingerprint:
                raise ImmutableObjectConflictError("Monitoring evidence ID has different content")

    def drift_reports(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[DriftReport, ...]:
        with self._lock:
            values = tuple(self._drift.values())
        return tuple(
            item
            for item in values
            if model_version_id is None or item.model_version_id == model_version_id
        )

    def performance_snapshots(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[PerformanceSnapshot, ...]:
        with self._lock:
            values = tuple(self._performance.values())
        return tuple(
            item
            for item in values
            if model_version_id is None
            or item.summary.model_version_id == model_version_id
        )

    def alerts(
        self, *, model_version_id: ModelVersionId | None = None
    ) -> tuple[MonitoringAlert, ...]:
        with self._lock:
            values = tuple(self._alerts.values())
        return tuple(
            item
            for item in values
            if model_version_id is None or item.model_version_id == model_version_id
        )
