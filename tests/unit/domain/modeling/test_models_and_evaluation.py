from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import ModelArtifactId, ModelVersionId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.evaluation import (
    CalibrationBin,
    ConfidenceInterval,
    EvaluationReport,
    FeatureImportance,
    MetricDirection,
    MetricValue,
    SliceEvaluation,
)
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelArtifact,
    ModelCard,
    ModelFamily,
    ModelSignature,
    ModelSpec,
    normalize_hyperparameter,
)


def make_spec(task=LearningTask.REGRESSION) -> ModelSpec:
    return ModelSpec(
        "ridge_model",
        "1.0.0",
        ModelFamily.LINEAR,
        task,
        "linear.ridge" if task is LearningTask.REGRESSION else "linear.logistic",
        42,
        (("alpha", Decimal("1.5")),),
    )


def test_model_spec_signature_and_parameters_are_canonical() -> None:
    spec = make_spec()
    signature = ModelSignature(("b", "a"), "future_return@1", LearningTask.REGRESSION)

    assert spec.parameter("alpha") == Decimal("1.5")
    assert spec.parameter("missing") is None
    assert spec.key == "ridge_model@1.0.0"
    assert len(spec.fingerprint) == 64
    assert len(signature.fingerprint) == 64
    assert normalize_hyperparameter(True, name="flag") is True
    assert normalize_hyperparameter(3, name="count") == 3
    assert normalize_hyperparameter(" value ", name="text") == "value"


def test_model_spec_rejects_unsafe_or_ambiguous_parameters() -> None:
    with pytest.raises(DomainValidationError, match="Decimal rather than float"):
        normalize_hyperparameter(0.1, name="alpha")
    with pytest.raises(DomainValidationError, match="cannot be blank"):
        normalize_hyperparameter(" ", name="name")
    with pytest.raises(DomainValidationError, match="Unsupported"):
        normalize_hyperparameter([], name="bad")
    with pytest.raises(DomainValidationError, match="Invalid model name"):
        ModelSpec("Bad Name", "1", ModelFamily.LINEAR, LearningTask.REGRESSION, "x", 0)
    with pytest.raises(DomainValidationError, match="cannot be negative"):
        ModelSpec("model", "1", ModelFamily.LINEAR, LearningTask.REGRESSION, "x", -1)
    with pytest.raises(DomainValidationError, match="unique"):
        ModelSpec(
            "model",
            "1",
            ModelFamily.LINEAR,
            LearningTask.REGRESSION,
            "x",
            1,
            (("alpha", 1), ("alpha", 2)),
        )
    with pytest.raises(DomainValidationError, match="unique feature"):
        ModelSignature(("a", "a"), "target", LearningTask.REGRESSION)


def test_model_artifact_and_card_preserve_lineage() -> None:
    spec = make_spec()
    signature = ModelSignature(("a", "b"), "future_return@1", LearningTask.REGRESSION)
    now = UtcInstant(datetime(2026, 1, 1, tzinfo=UTC))
    version = ModelVersionId.new()
    artifact = ModelArtifact(
        ModelArtifactId.new(),
        version,
        spec,
        signature,
        "application/test",
        b"model-bytes",
        now,
    )
    artifact.verify()
    assert len(artifact.payload_sha256) == 64

    card = ModelCard.create(
        model_version_id=version,
        spec=spec,
        intended_use="Research",
        prohibited_uses=("Live trading",),
        training_dataset_fingerprint="a" * 64,
        split_plan_fingerprint="b" * 64,
        primary_metric="mae",
        cross_validation_score="0.1",
        holdout_score="0.2",
        limitations=("Regime change",),
        generated_at=now,
    )
    assert card.holdout_score == Decimal("0.2")

    with pytest.raises(DomainValidationError, match="tasks must match"):
        replace(
            artifact,
            signature=ModelSignature(
                ("a", "b"),
                "future_return@1",
                LearningTask.BINARY_CLASSIFICATION,
            ),
        )
    with pytest.raises(DomainValidationError, match="prohibited uses"):
        replace(card, prohibited_uses=())


def test_metric_values_reports_and_evidence_validate() -> None:
    mae = MetricValue("mae", "0.1", MetricDirection.MINIMIZE)
    worse = MetricValue("mae", "0.2", MetricDirection.MINIMIZE)
    assert mae.better_than(worse)
    with pytest.raises(DomainValidationError, match="matching"):
        mae.better_than(MetricValue("rmse", "0.1", MetricDirection.MINIMIZE))

    calibration = CalibrationBin("0", "0.5", 3, "0.2", "0.333")
    importance = FeatureImportance("momentum", "0.02", "0.01", 5)
    interval = ConfidenceInterval("mae", "0.95", "0.05", "0.1", "0.2")
    slice_report = SliceEvaluation("year", "2025", 3, (mae,))
    report = EvaluationReport(
        LearningTask.REGRESSION,
        3,
        (mae,),
        (calibration,),
        (slice_report,),
        UtcInstant(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    assert report.metric("MAE") == mae
    assert importance.repetitions == 5
    assert interval.point_estimate == Decimal("0.1")
    assert len(report.fingerprint) == 64
    with pytest.raises(DomainValidationError, match="not present"):
        report.metric("r2")


def test_evaluation_evidence_rejects_invalid_ranges() -> None:
    with pytest.raises(DomainValidationError, match="partition"):
        CalibrationBin("0.5", "0.5", 1, "0.5", "0.5")
    with pytest.raises(DomainValidationError, match="cannot be empty"):
        CalibrationBin("0", "1", 0, "0.5", "0.5")
    with pytest.raises(DomainValidationError, match="Invalid feature"):
        FeatureImportance("", "0", "-1", 0)
    with pytest.raises(DomainValidationError, match="contain point"):
        ConfidenceInterval("mae", "0.95", "0.2", "0.1", "0.3")
    with pytest.raises(DomainValidationError, match="requires samples"):
        SliceEvaluation("year", "2025", 0, ())
