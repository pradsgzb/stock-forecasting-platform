from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import numpy as np
import pytest

from stock_predictor.adapters.repositories.in_memory_monitoring_repository import (
    InMemoryMonitoringRepository,
)
from stock_predictor.application.monitoring.service import (
    DriftPolicy,
    ModelMonitoringService,
    PerformancePolicy,
)
from stock_predictor.domain.common.errors import DomainValidationError, MonitoringError
from stock_predictor.domain.common.identifiers import ModelVersionId
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.mlops.feedback import FeedbackMetric, FeedbackSummary
from stock_predictor.domain.mlops.monitoring import DriftKind, MonitoringSeverity
from tests.helpers.mlops import fixed_clock


def _windows(now):
    reference = InstantInterval(
        now.plus(-timedelta(days=4)), now.plus(-timedelta(days=3))
    )
    current = InstantInterval(
        now.plus(-timedelta(days=2)), now.plus(-timedelta(days=1))
    )
    return reference, current


def _summary(now, model_id, *, target="future_return@1.0.0", samples=10, **values):
    metrics = tuple(FeedbackMetric(name, value) for name, value in values.items())
    window = InstantInterval(now.plus(-timedelta(days=1)), now)
    return FeedbackSummary(
        model_version_id=model_id,
        target_key=target,
        window=window,
        sample_count=samples,
        metrics=metrics,
        generated_at=now,
        outcome_fingerprints=tuple(f"{index:064x}" for index in range(samples)),
    )


def test_detects_critical_distribution_drift_and_persists_alert(fixed_instant) -> None:
    repository = InMemoryMonitoringRepository()
    service = ModelMonitoringService(
        repository,
        fixed_clock(fixed_instant),
        drift_policy=DriftPolicy(
            minimum_samples=4,
            histogram_bins=3,
            psi_warning=Decimal("0.01"),
            psi_critical=Decimal("0.02"),
            mean_shift_warning=Decimal("0.1"),
            mean_shift_critical=Decimal("0.2"),
            missing_delta_warning=Decimal("0.1"),
            missing_delta_critical=Decimal("0.2"),
            js_warning=Decimal("0.01"),
            js_critical=Decimal("0.02"),
        ),
    )
    model_id = ModelVersionId.new()
    reference_window, current_window = _windows(fixed_instant)
    report = service.detect_distribution_drift(
        model_version_id=model_id,
        kind=DriftKind.FEATURE,
        subject_key="momentum@1.0.0",
        reference_values=(Decimal("1"), Decimal("2"), Decimal("3"), None),
        current_values=(Decimal("20"), Decimal("21"), None, None),
        reference_window=reference_window,
        current_window=current_window,
    )
    assert report.severity is MonitoringSeverity.CRITICAL
    assert len(repository.drift_reports(model_version_id=model_id)) == 1
    alert = repository.alerts(model_version_id=model_id)[0]
    assert alert.category == "feature_drift"
    assert alert.evidence_reference == report.fingerprint


def test_no_drift_alert_for_stable_constant_distribution(fixed_instant) -> None:
    repository = InMemoryMonitoringRepository()
    service = ModelMonitoringService(
        repository,
        fixed_clock(fixed_instant),
        drift_policy=DriftPolicy(minimum_samples=4, histogram_bins=3),
    )
    reference_window, current_window = _windows(fixed_instant)
    report = service.detect_distribution_drift(
        model_version_id=ModelVersionId.new(),
        kind=DriftKind.PREDICTION,
        subject_key="predicted_return",
        reference_values=(Decimal("1"),) * 4,
        current_values=(Decimal("1"),) * 4,
        reference_window=reference_window,
        current_window=current_window,
    )
    assert report.severity is MonitoringSeverity.INFORMATIONAL
    assert repository.alerts() == ()


def test_drift_validation_and_non_finite_data(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="two samples"):
        DriftPolicy(minimum_samples=1)
    with pytest.raises(DomainValidationError, match="precede"):
        DriftPolicy(psi_warning=Decimal("0.2"), psi_critical=Decimal("0.1"))
    service = ModelMonitoringService(
        InMemoryMonitoringRepository(),
        fixed_clock(fixed_instant),
        drift_policy=DriftPolicy(minimum_samples=3),
    )
    reference_window, current_window = _windows(fixed_instant)
    with pytest.raises(MonitoringError, match="fewer"):
        service.detect_distribution_drift(
            model_version_id=ModelVersionId.new(),
            kind=DriftKind.FEATURE,
            subject_key="x",
            reference_values=(1, 2),
            current_values=(1, 2),
            reference_window=reference_window,
            current_window=current_window,
        )
    with pytest.raises(MonitoringError, match="numeric"):
        service.detect_distribution_drift(
            model_version_id=ModelVersionId.new(),
            kind=DriftKind.FEATURE,
            subject_key="x",
            reference_values=(None, None, 1),
            current_values=(None, None, 2),
            reference_window=reference_window,
            current_window=current_window,
        )
    with pytest.raises(MonitoringError, match="finite"):
        service.detect_distribution_drift(
            model_version_id=ModelVersionId.new(),
            kind=DriftKind.FEATURE,
            subject_key="x",
            reference_values=(1, 2, 3),
            current_values=(1, 2, Decimal("NaN")),
            reference_window=reference_window,
            current_window=current_window,
        )
    with pytest.raises(MonitoringError, match="non-finite"):
        service._decimal(np.inf)


def test_records_performance_degradation_and_directional_alert(fixed_instant) -> None:
    repository = InMemoryMonitoringRepository()
    model_id = ModelVersionId.new()
    policy = PerformancePolicy(
        minimum_samples=3,
        degradation_warning=Decimal("0.10"),
        degradation_critical=Decimal("0.20"),
        directional_accuracy_warning=Decimal("0.55"),
        directional_accuracy_critical=Decimal("0.45"),
    )
    service = ModelMonitoringService(
        repository, fixed_clock(fixed_instant), performance_policy=policy
    )
    baseline = _summary(
        fixed_instant,
        model_id,
        mae="0.10",
        rmse="0.20",
        bias="0.01",
        directional_accuracy="0.70",
        brier_score="0.10",
    )
    current = _summary(
        fixed_instant,
        model_id,
        mae="0.15",
        rmse="0.30",
        bias="0.03",
        directional_accuracy="0.40",
        brier_score="0.20",
    )
    snapshot = service.record_performance(current, baseline=baseline)
    assert snapshot.severity is MonitoringSeverity.CRITICAL
    assert dict(snapshot.metric_degradation)["mae"] == Decimal("0.5")
    assert repository.alerts()[0].category == "performance_degradation"


def test_performance_handles_no_directional_metric_and_validates_inputs(
    fixed_instant,
) -> None:
    with pytest.raises(DomainValidationError, match="sample count"):
        PerformancePolicy(minimum_samples=0)
    with pytest.raises(DomainValidationError, match="degradation"):
        PerformancePolicy(degradation_warning=Decimal("0.3"), degradation_critical=Decimal("0.2"))
    with pytest.raises(DomainValidationError, match="Directional"):
        PerformancePolicy(
            directional_accuracy_critical=Decimal("0.6"),
            directional_accuracy_warning=Decimal("0.5"),
        )
    repository = InMemoryMonitoringRepository()
    model_id = ModelVersionId.new()
    service = ModelMonitoringService(
        repository,
        fixed_clock(fixed_instant),
        performance_policy=PerformancePolicy(minimum_samples=2),
    )
    summary = _summary(fixed_instant, model_id, samples=2, mae="0.1")
    snapshot = service.record_performance(summary)
    assert snapshot.severity is MonitoringSeverity.INFORMATIONAL
    assert repository.alerts() == ()
    with pytest.raises(MonitoringError, match="fewer"):
        service.record_performance(_summary(fixed_instant, model_id, samples=1, mae="0.1"))
    different = _summary(
        fixed_instant,
        model_id,
        target="different@1",
        samples=2,
        mae="0.1",
    )
    with pytest.raises(MonitoringError, match="target"):
        service.record_performance(summary, baseline=different)


def test_degradation_rules_cover_error_accuracy_bias_and_unknown(fixed_instant) -> None:
    service = ModelMonitoringService(
        InMemoryMonitoringRepository(), fixed_clock(fixed_instant)
    )
    assert service._degradation("mae", Decimal(0), Decimal("0.1")) > 0
    assert service._degradation(
        "directional_accuracy", Decimal("0.8"), Decimal("0.6")
    ) == Decimal("0.2")
    assert service._degradation("bias", Decimal("0.1"), Decimal("0.2")) == Decimal(1)
    assert service._degradation("unknown", Decimal(1), Decimal(2)) == Decimal(0)
