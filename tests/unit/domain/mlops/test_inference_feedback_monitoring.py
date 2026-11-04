from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    DriftReportId,
    FeatureSnapshotId,
    InstrumentId,
    LabelId,
    ModelVersionId,
    MonitoringAlertId,
    MonitoringSnapshotId,
    OutcomeId,
    PredictionBatchId,
    PredictionId,
)
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.common.values import Probability
from stock_predictor.domain.mlops.feedback import (
    FeedbackMetric,
    FeedbackSummary,
    RealizedOutcome,
)
from stock_predictor.domain.mlops.inference import (
    PredictionBatch,
    PredictionBatchStatus,
    PredictionFailure,
    PredictionRecord,
)
from stock_predictor.domain.mlops.monitoring import (
    DriftKind,
    DriftMeasure,
    DriftReport,
    MonitoringAlert,
    MonitoringSeverity,
    PerformanceSnapshot,
)
from tests.helpers.mlops import scope
from tests.helpers.modeling import regression_target


def _prediction(fixed_instant, *, correction_of=None):
    target = regression_target()
    return PredictionRecord(
        prediction_id=PredictionId.new(),
        batch_id=PredictionBatchId.new(),
        scope=scope(target),
        instrument_id=InstrumentId.new(),
        as_of=date(2026, 1, 2),
        decision_cutoff=fixed_instant,
        generated_at=fixed_instant,
        horizon=target.horizon,
        model_version_id=ModelVersionId.new(),
        artifact_sha256="a" * 64,
        signature_fingerprint="b" * 64,
        feature_snapshot_id=FeatureSnapshotId.new(),
        feature_snapshot_fingerprint="c" * 64,
        input_fingerprint="d" * 64,
        predicted_value="0.10",
        positive_probability=Probability("0.7"),
        interval_lower="0.05",
        interval_upper="0.15",
        expected_volatility="0.20",
        cross_sectional_rank=Probability("0.8"),
        confidence=Probability("0.4"),
        correction_of=correction_of,
    )


def test_prediction_record_captures_lineage(fixed_instant) -> None:
    prediction = _prediction(fixed_instant)
    assert prediction.predicted_value == Decimal("0.10")
    assert prediction.positive_probability == Probability("0.7")
    assert len(prediction.fingerprint) == 64


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"artifact_sha256": "bad"}, "fingerprints"),
        ({"interval_lower": "0.20", "interval_upper": "0.30"}, "interval"),
        ({"expected_volatility": "-0.1"}, "volatility"),
    ],
)
def test_prediction_record_rejects_invalid_values(fixed_instant, changes, match) -> None:
    prediction = _prediction(fixed_instant)
    values = {
        name: getattr(prediction, name)
        for name in (
            "prediction_id",
            "batch_id",
            "scope",
            "instrument_id",
            "as_of",
            "decision_cutoff",
            "generated_at",
            "horizon",
            "model_version_id",
            "artifact_sha256",
            "signature_fingerprint",
            "feature_snapshot_id",
            "feature_snapshot_fingerprint",
            "input_fingerprint",
            "predicted_value",
            "positive_probability",
            "interval_lower",
            "interval_upper",
            "expected_volatility",
            "cross_sectional_rank",
            "confidence",
            "correction_of",
        )
    }
    values.update(changes)
    with pytest.raises(DomainValidationError, match=match):
        PredictionRecord(**values)


def test_prediction_batch_status_invariants(fixed_instant) -> None:
    prediction = _prediction(fixed_instant)
    batch = PredictionBatch(
        prediction.batch_id,
        "batch-key",
        "e" * 64,
        prediction.scope,
        prediction.model_version_id,
        "f" * 64,
        "1" * 64,
        fixed_instant,
        fixed_instant,
        PredictionBatchStatus.COMPLETED,
        (prediction,),
        (),
    )
    assert len(batch.fingerprint) == 64
    failure = PredictionFailure(InstrumentId.new(), "feature_error", "missing")
    with pytest.raises(DomainValidationError, match="Completed"):
        PredictionBatch(
            prediction.batch_id,
            "other-key",
            "e" * 64,
            prediction.scope,
            prediction.model_version_id,
            "f" * 64,
            "1" * 64,
            fixed_instant,
            fixed_instant,
            PredictionBatchStatus.COMPLETED,
            (prediction,),
            (failure,),
        )


def test_realized_outcome_calculates_errors(fixed_instant) -> None:
    prediction = _prediction(fixed_instant)
    outcome = RealizedOutcome(
        outcome_id=OutcomeId.new(),
        prediction_id=prediction.prediction_id,
        model_version_id=prediction.model_version_id,
        instrument_id=prediction.instrument_id,
        target_key=prediction.scope.target_key,
        as_of=prediction.as_of,
        horizon_end=prediction.as_of + timedelta(days=1),
        observed_at=fixed_instant,
        source_label_id=LabelId.new(),
        source_label_fingerprint="a" * 64,
        prediction_value="0.10",
        actual_value="0.04",
        positive_probability=Probability("0.7"),
        direction_correct=True,
        revision=1,
    )
    assert outcome.error == Decimal("0.06")
    assert outcome.absolute_error == Decimal("0.06")
    assert outcome.squared_error == Decimal("0.0036")


def test_outcome_revision_invariants(fixed_instant) -> None:
    prediction = _prediction(fixed_instant)
    with pytest.raises(DomainValidationError, match="revision"):
        RealizedOutcome(
            outcome_id=OutcomeId.new(),
            prediction_id=prediction.prediction_id,
            model_version_id=prediction.model_version_id,
            instrument_id=prediction.instrument_id,
            target_key=prediction.scope.target_key,
            as_of=prediction.as_of,
            horizon_end=prediction.as_of + timedelta(days=1),
            observed_at=fixed_instant,
            source_label_id=LabelId.new(),
            source_label_fingerprint="a" * 64,
            prediction_value="0.1",
            actual_value="0.1",
            positive_probability=None,
            direction_correct=True,
            revision=2,
        )


def test_feedback_summary_metric_lookup(fixed_instant) -> None:
    window = InstantInterval(fixed_instant, fixed_instant.plus(timedelta(hours=1)))
    summary = FeedbackSummary(
        ModelVersionId.new(),
        "future_return@1.0.0",
        window,
        1,
        (FeedbackMetric("mae", "0.1"),),
        window.end,
        ("a" * 64,),
    )
    assert summary.metric("MAE").value == Decimal("0.1")
    with pytest.raises(DomainValidationError):
        summary.metric("rmse")


def test_drift_measure_and_report_severity(fixed_instant) -> None:
    reference = InstantInterval(
        fixed_instant.plus(-timedelta(hours=2)),
        fixed_instant.plus(-timedelta(hours=1)),
    )
    current = InstantInterval(
        fixed_instant.plus(-timedelta(hours=1)),
        fixed_instant,
    )
    measure = DriftMeasure("psi", "0.30", "0.10", "0.25")
    report = DriftReport(
        DriftReportId.new(),
        ModelVersionId.new(),
        DriftKind.FEATURE,
        "momentum@1.0.0",
        reference,
        current,
        100,
        100,
        (measure,),
        fixed_instant,
    )
    assert measure.severity is MonitoringSeverity.CRITICAL
    assert report.severity is MonitoringSeverity.CRITICAL
    assert len(report.fingerprint) == 64


def test_drift_report_rejects_overlapping_windows(fixed_instant) -> None:
    reference = InstantInterval(
        fixed_instant.plus(-timedelta(hours=2)), fixed_instant
    )
    current = InstantInterval(
        fixed_instant.plus(-timedelta(hours=1)), fixed_instant.plus(timedelta(hours=1))
    )
    with pytest.raises(DomainValidationError, match="follow"):
        DriftReport(
            DriftReportId.new(),
            ModelVersionId.new(),
            DriftKind.PREDICTION,
            "score",
            reference,
            current,
            30,
            30,
            (DriftMeasure("psi", "0.01", "0.1", "0.2"),),
            current.end,
        )


def test_performance_snapshot_and_alert_validate(fixed_instant) -> None:
    window = InstantInterval(
        fixed_instant.plus(-timedelta(hours=1)), fixed_instant
    )
    summary = FeedbackSummary(
        ModelVersionId.new(),
        "future_return@1.0.0",
        window,
        1,
        (FeedbackMetric("mae", "0.1"),),
        fixed_instant,
        ("a" * 64,),
    )
    snapshot = PerformanceSnapshot(
        MonitoringSnapshotId.new(),
        summary,
        None,
        (("mae", Decimal("0.2")),),
        MonitoringSeverity.WARNING,
        fixed_instant,
    )
    alert = MonitoringAlert(
        MonitoringAlertId.new(),
        summary.model_version_id,
        MonitoringSeverity.WARNING,
        "performance_degradation",
        "Review model",
        "Metric crossed threshold",
        snapshot.fingerprint,
        fixed_instant,
    )
    assert alert.category == "performance_degradation"
