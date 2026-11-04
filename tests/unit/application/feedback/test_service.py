from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from stock_predictor.adapters.repositories.in_memory_outcome_repository import (
    InMemoryOutcomeRepository,
)
from stock_predictor.adapters.repositories.in_memory_prediction_ledger import (
    InMemoryPredictionLedger,
)
from stock_predictor.application.feedback.service import (
    FeedbackService,
    OutcomeCollectionService,
)
from stock_predictor.domain.common.errors import FeedbackError
from stock_predictor.domain.common.identifiers import (
    FeatureSnapshotId,
    InstrumentId,
    LabelId,
    ModelVersionId,
    PredictionBatchId,
    PredictionId,
)
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.common.values import Probability
from stock_predictor.domain.mlops.inference import (
    PredictionBatch,
    PredictionBatchStatus,
    PredictionRecord,
)
from stock_predictor.domain.modeling.targets import LabelObservation
from tests.helpers.mlops import StubLabelService, fixed_clock, scope
from tests.helpers.modeling import classification_target, regression_target


def _prediction(now, target, *, predicted: str = "0.10", probability: str | None = "0.70"):
    batch_id = PredictionBatchId.new()
    model_id = ModelVersionId.new()
    prediction = PredictionRecord(
        prediction_id=PredictionId.new(),
        batch_id=batch_id,
        scope=scope(target),
        instrument_id=InstrumentId.new(),
        as_of=date(2026, 1, 2),
        decision_cutoff=now,
        generated_at=now,
        horizon=target.horizon,
        model_version_id=model_id,
        artifact_sha256="a" * 64,
        signature_fingerprint="b" * 64,
        feature_snapshot_id=FeatureSnapshotId.new(),
        feature_snapshot_fingerprint="c" * 64,
        input_fingerprint="d" * 64,
        predicted_value=predicted,
        positive_probability=(Probability(probability) if probability is not None else None),
    )
    batch = PredictionBatch(
        batch_id=batch_id,
        idempotency_key=f"batch-{prediction.prediction_id}",
        request_fingerprint="e" * 64,
        scope=prediction.scope,
        model_version_id=model_id,
        target_definition_fingerprint=target.fingerprint,
        feature_set_fingerprint="f" * 64,
        started_at=now,
        completed_at=now,
        status=PredictionBatchStatus.COMPLETED,
        predictions=(prediction,),
        failures=(),
    )
    return prediction, batch


def _window(now):
    return InstantInterval(now.plus(-timedelta(minutes=1)), now)


def test_collects_revises_and_summarizes_realized_outcomes(fixed_instant) -> None:
    target = regression_target()
    prediction, batch = _prediction(fixed_instant, target)
    ledger = InMemoryPredictionLedger()
    ledger.append_batch(batch)
    outcomes = InMemoryOutcomeRepository()
    labels = StubLabelService(target, Decimal("0.20"))
    collector = OutcomeCollectionService(
        ledger,
        outcomes,
        labels,
        fixed_clock(fixed_instant.plus(-timedelta(seconds=30))),
    )

    first = collector.collect(target, fixed_instant)
    assert len(first.collected) == 1
    assert first.collected[0].revision == 1
    assert first.collected[0].absolute_error == Decimal("0.10")
    assert first.collected[0].direction_correct

    unchanged = collector.collect(target, fixed_instant)
    assert unchanged.unchanged_prediction_ids == (prediction.prediction_id,)

    labels.actual = Decimal("-0.05")
    from stock_predictor.domain.common.identifiers import PriceBarId

    labels.source_bar_id = PriceBarId.new()
    revised = collector.collect(
        target, fixed_instant, prediction_ids=(prediction.prediction_id,)
    )
    assert revised.collected[0].revision == 2
    assert revised.collected[0].supersedes == first.collected[0].outcome_id
    assert not revised.collected[0].direction_correct

    summary = FeedbackService(outcomes, fixed_clock(fixed_instant)).summarize(
        prediction.model_version_id, target.key, _window(fixed_instant)
    )
    assert summary.sample_count == 1
    assert summary.metric("mae").value == Decimal("0.15")
    assert summary.metric("rmse").value == Decimal("0.15")
    assert summary.metric("bias").value == Decimal("0.15")
    assert summary.metric("directional_accuracy").value == Decimal(0)
    assert summary.metric("brier_score").value == Decimal("0.5625")


def test_binary_outcome_uses_probability_threshold(fixed_instant) -> None:
    target = classification_target()
    prediction, batch = _prediction(fixed_instant, target, predicted="0.80")
    ledger = InMemoryPredictionLedger()
    ledger.append_batch(batch)
    outcomes = InMemoryOutcomeRepository()
    labels = StubLabelService(target, 1)
    result = OutcomeCollectionService(
        ledger, outcomes, labels, fixed_clock(fixed_instant)
    ).collect(target, fixed_instant)
    assert result.collected[0].direction_correct
    assert result.collected[0].actual_value == Decimal(1)
    assert result.collected[0].prediction_id == prediction.prediction_id


def test_collection_reports_target_mismatch_label_failure_and_missing_label(
    fixed_instant,
) -> None:
    target = regression_target()
    prediction, batch = _prediction(fixed_instant, target)
    ledger = InMemoryPredictionLedger()
    ledger.append_batch(batch)
    outcomes = InMemoryOutcomeRepository()

    other = classification_target()
    mismatch = OutcomeCollectionService(
        ledger, outcomes, StubLabelService(other), fixed_clock(fixed_instant)
    ).collect(other, fixed_instant, prediction_ids=(prediction.prediction_id,))
    assert "does not match" in mismatch.failures[0].reason

    failing = StubLabelService(target)
    failing.fail = True
    failed = OutcomeCollectionService(
        ledger, outcomes, failing, fixed_clock(fixed_instant)
    ).collect(target, fixed_instant)
    assert "not mature" in failed.failures[0].reason

    class MissingLabelService:
        def calculate(self, target, instrument_id, as_of, outcome_cutoff):
            return LabelObservation(
                LabelId.new(),
                target,
                instrument_id,
                as_of,
                as_of + timedelta(days=1),
                outcome_cutoff,
                outcome_cutoff,
                None,
                "market observation unavailable",
                (),
            )

    missing = OutcomeCollectionService(
        ledger, outcomes, MissingLabelService(), fixed_clock(fixed_instant)
    ).collect(target, fixed_instant)
    assert "unavailable" in missing.failures[0].reason


def test_feedback_summary_rejects_empty_window(fixed_instant) -> None:
    service = FeedbackService(InMemoryOutcomeRepository(), fixed_clock(fixed_instant))
    with pytest.raises(FeedbackError, match="No realized outcomes"):
        service.summarize(ModelVersionId.new(), "future_return@1.0.0", _window(fixed_instant))
