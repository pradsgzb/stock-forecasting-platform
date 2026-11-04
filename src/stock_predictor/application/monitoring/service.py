"""Distribution-drift and realized-performance monitoring services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import DomainValidationError, MonitoringError
from stock_predictor.domain.common.identifiers import (
    DriftReportId,
    ModelVersionId,
    MonitoringAlertId,
    MonitoringSnapshotId,
)
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.common.values import to_decimal
from stock_predictor.domain.mlops.feedback import FeedbackSummary
from stock_predictor.domain.mlops.monitoring import (
    DriftKind,
    DriftMeasure,
    DriftReport,
    MonitoringAlert,
    MonitoringSeverity,
    PerformanceSnapshot,
)
from stock_predictor.ports.monitoring_repository import MonitoringRepository

FloatArray = NDArray[np.float64]
NumericObservation = Decimal | int | None


@dataclass(frozen=True, slots=True)
class DriftPolicy:
    minimum_samples: int = 30
    histogram_bins: int = 10
    psi_warning: Decimal = Decimal("0.10")
    psi_critical: Decimal = Decimal("0.25")
    mean_shift_warning: Decimal = Decimal("0.50")
    mean_shift_critical: Decimal = Decimal("1.00")
    missing_delta_warning: Decimal = Decimal("0.05")
    missing_delta_critical: Decimal = Decimal("0.15")
    js_warning: Decimal = Decimal("0.05")
    js_critical: Decimal = Decimal("0.15")

    def __post_init__(self) -> None:
        if self.minimum_samples < 2 or self.histogram_bins < 2:
            raise DomainValidationError("Drift policy requires at least two samples and bins")
        pairs = (
            (self.psi_warning, self.psi_critical),
            (self.mean_shift_warning, self.mean_shift_critical),
            (self.missing_delta_warning, self.missing_delta_critical),
            (self.js_warning, self.js_critical),
        )
        if any(warning < 0 or critical <= warning for warning, critical in pairs):
            raise DomainValidationError("Drift warning thresholds must precede critical thresholds")


@dataclass(frozen=True, slots=True)
class PerformancePolicy:
    minimum_samples: int = 30
    degradation_warning: Decimal = Decimal("0.10")
    degradation_critical: Decimal = Decimal("0.25")
    directional_accuracy_warning: Decimal = Decimal("0.50")
    directional_accuracy_critical: Decimal = Decimal("0.45")

    def __post_init__(self) -> None:
        if self.minimum_samples <= 0:
            raise DomainValidationError("Performance policy sample count must be positive")
        if not Decimal(0) <= self.degradation_warning < self.degradation_critical:
            raise DomainValidationError("Performance degradation thresholds are invalid")
        if not (
            Decimal(0)
            <= self.directional_accuracy_critical
            < self.directional_accuracy_warning
            <= Decimal(1)
        ):
            raise DomainValidationError("Directional accuracy thresholds are invalid")


class ModelMonitoringService:
    __slots__ = ("_clock", "_drift_policy", "_performance_policy", "_repository")

    def __init__(
        self,
        repository: MonitoringRepository,
        clock: Clock,
        *,
        drift_policy: DriftPolicy = DriftPolicy(),
        performance_policy: PerformancePolicy = PerformancePolicy(),
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._drift_policy = drift_policy
        self._performance_policy = performance_policy

    def detect_distribution_drift(
        self,
        *,
        model_version_id: ModelVersionId,
        kind: DriftKind,
        subject_key: str,
        reference_values: tuple[NumericObservation, ...],
        current_values: tuple[NumericObservation, ...],
        reference_window: InstantInterval,
        current_window: InstantInterval,
    ) -> DriftReport:
        policy = self._drift_policy
        if len(reference_values) < policy.minimum_samples or len(current_values) < (
            policy.minimum_samples
        ):
            raise MonitoringError("Drift analysis has fewer than the required samples")
        reference, reference_missing = self._numeric(reference_values)
        current, current_missing = self._numeric(current_values)
        if len(reference) < 2 or len(current) < 2:
            raise MonitoringError("Drift analysis requires at least two numeric observations")
        reference_distribution, current_distribution = self._histograms(
            reference, current, policy.histogram_bins
        )
        psi = self._psi(reference_distribution, current_distribution)
        js = self._jensen_shannon(reference_distribution, current_distribution)
        reference_std = float(np.std(reference))
        denominator = reference_std
        if denominator <= 1e-12:
            denominator = max(abs(float(np.mean(reference))), 1.0)
        mean_shift = abs(float(np.mean(current)) - float(np.mean(reference))) / denominator
        missing_delta = abs(current_missing - reference_missing)
        measures = (
            DriftMeasure(
                "population_stability_index",
                self._decimal(psi),
                policy.psi_warning,
                policy.psi_critical,
            ),
            DriftMeasure(
                "jensen_shannon_divergence",
                self._decimal(js),
                policy.js_warning,
                policy.js_critical,
            ),
            DriftMeasure(
                "standardized_mean_shift",
                self._decimal(mean_shift),
                policy.mean_shift_warning,
                policy.mean_shift_critical,
            ),
            DriftMeasure(
                "missing_rate_delta",
                self._decimal(missing_delta),
                policy.missing_delta_warning,
                policy.missing_delta_critical,
            ),
        )
        report = DriftReport(
            report_id=DriftReportId.new(),
            model_version_id=model_version_id,
            kind=kind,
            subject_key=subject_key,
            reference_window=reference_window,
            current_window=current_window,
            reference_sample_count=len(reference_values),
            current_sample_count=len(current_values),
            measures=measures,
            created_at=self._clock.now(),
        )
        self._repository.append_drift_report(report)
        self._alert_for_drift(report)
        return report

    def record_performance(
        self,
        summary: FeedbackSummary,
        *,
        baseline: FeedbackSummary | None = None,
    ) -> PerformanceSnapshot:
        policy = self._performance_policy
        if summary.sample_count < policy.minimum_samples:
            raise MonitoringError("Performance summary has fewer than required outcomes")
        degradation: list[tuple[str, Decimal]] = []
        severity = MonitoringSeverity.INFORMATIONAL
        if baseline is not None:
            if baseline.target_key != summary.target_key:
                raise MonitoringError("Performance baseline target differs from current summary")
            baseline_metrics = {item.name: item.value for item in baseline.metrics}
            for metric in summary.metrics:
                if metric.name not in baseline_metrics:
                    continue
                value = self._degradation(
                    metric.name,
                    baseline_metrics[metric.name],
                    metric.value,
                )
                degradation.append((metric.name, value))
                severity = max(severity, self._degradation_severity(value))
        try:
            directional = summary.metric("directional_accuracy").value
        except DomainValidationError:
            directional = None
        if directional is not None:
            if directional <= policy.directional_accuracy_critical:
                severity = MonitoringSeverity.CRITICAL
            elif directional <= policy.directional_accuracy_warning:
                severity = max(severity, MonitoringSeverity.WARNING)
        snapshot = PerformanceSnapshot(
            snapshot_id=MonitoringSnapshotId.new(),
            summary=summary,
            baseline_summary_fingerprint=baseline.fingerprint if baseline else None,
            metric_degradation=tuple(degradation),
            severity=severity,
            created_at=self._clock.now(),
        )
        self._repository.append_performance_snapshot(snapshot)
        if severity is not MonitoringSeverity.INFORMATIONAL:
            self._repository.append_alert(
                MonitoringAlert(
                    alert_id=MonitoringAlertId.new(),
                    model_version_id=summary.model_version_id,
                    severity=severity,
                    category="performance_degradation",
                    title="Model performance requires review",
                    detail=(
                        "Realized performance crossed configured warning or critical thresholds."
                    ),
                    evidence_reference=snapshot.fingerprint,
                    raised_at=self._clock.now(),
                )
            )
        return snapshot

    def _alert_for_drift(self, report: DriftReport) -> None:
        if report.severity is MonitoringSeverity.INFORMATIONAL:
            return
        self._repository.append_alert(
            MonitoringAlert(
                alert_id=MonitoringAlertId.new(),
                model_version_id=report.model_version_id,
                severity=report.severity,
                category=f"{report.kind.value}_drift",
                title=f"{report.kind.value.replace('_', ' ').title()} drift detected",
                detail=(
                    f"Distribution drift for {report.subject_key} crossed configured thresholds."
                ),
                evidence_reference=report.fingerprint,
                raised_at=self._clock.now(),
            )
        )

    def _degradation_severity(self, value: Decimal) -> MonitoringSeverity:
        if value >= self._performance_policy.degradation_critical:
            return MonitoringSeverity.CRITICAL
        if value >= self._performance_policy.degradation_warning:
            return MonitoringSeverity.WARNING
        return MonitoringSeverity.INFORMATIONAL

    @staticmethod
    def _degradation(name: str, baseline: Decimal, current: Decimal) -> Decimal:
        if name in {"mae", "rmse", "brier_score"}:
            denominator = max(abs(baseline), Decimal("0.000000000001"))
            return max((current - baseline) / denominator, Decimal(0))
        if name == "directional_accuracy":
            return max(baseline - current, Decimal(0))
        if name == "bias":
            denominator = max(abs(baseline), Decimal("0.000000000001"))
            return max((abs(current) - abs(baseline)) / denominator, Decimal(0))
        return Decimal(0)

    @staticmethod
    def _numeric(
        values: tuple[NumericObservation, ...],
    ) -> tuple[FloatArray, float]:
        numeric = np.asarray(
            [float(item) for item in values if item is not None],
            dtype=np.float64,
        )
        if not np.isfinite(numeric).all():
            raise MonitoringError("Monitoring values must be finite")
        missing_rate = (len(values) - len(numeric)) / len(values)
        return numeric, missing_rate

    @staticmethod
    def _histograms(
        reference: FloatArray,
        current: FloatArray,
        bin_count: int,
    ) -> tuple[FloatArray, FloatArray]:
        quantiles = np.linspace(0, 1, bin_count + 1)
        edges = np.unique(np.quantile(reference, quantiles))
        if len(edges) < 2:
            center = float(reference[0])
            edges = np.asarray([center - 0.5, center + 0.5], dtype=np.float64)
        edges[0] = -np.inf
        edges[-1] = np.inf
        reference_counts, _ = np.histogram(reference, bins=edges)
        current_counts, _ = np.histogram(current, bins=edges)
        epsilon = 1e-6
        reference_distribution = (reference_counts + epsilon) / (
            np.sum(reference_counts) + epsilon * len(reference_counts)
        )
        current_distribution = (current_counts + epsilon) / (
            np.sum(current_counts) + epsilon * len(current_counts)
        )
        return reference_distribution, current_distribution

    @staticmethod
    def _psi(reference: FloatArray, current: FloatArray) -> float:
        return float(np.sum((current - reference) * np.log(current / reference)))

    @staticmethod
    def _jensen_shannon(reference: FloatArray, current: FloatArray) -> float:
        midpoint = (reference + current) / 2
        divergence = 0.5 * np.sum(reference * np.log(reference / midpoint))
        divergence += 0.5 * np.sum(current * np.log(current / midpoint))
        return float(divergence)

    @staticmethod
    def _decimal(value: float | np.float64) -> Decimal:
        if not np.isfinite(value):
            raise MonitoringError("Monitoring calculation produced a non-finite value")
        return to_decimal(str(float(value)), field_name="monitoring metric")
