"""Outcome collection and feedback aggregation services."""

from __future__ import annotations

from decimal import Decimal, localcontext

from stock_predictor.application.labels.service import TargetLabelService
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import FeedbackError, LabelComputationError
from stock_predictor.domain.common.identifiers import ModelVersionId, OutcomeId, PredictionId
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.mlops.feedback import (
    FeedbackMetric,
    FeedbackSummary,
    OutcomeCollectionFailure,
    OutcomeCollectionResult,
    RealizedOutcome,
)
from stock_predictor.domain.modeling.targets import TargetDefinition, TargetValueType
from stock_predictor.ports.outcome_repository import OutcomeRepository
from stock_predictor.ports.prediction_ledger import PredictionLedger


class OutcomeCollectionService:
    __slots__ = ("_clock", "_labels", "_ledger", "_outcomes")

    def __init__(
        self,
        ledger: PredictionLedger,
        outcomes: OutcomeRepository,
        labels: TargetLabelService,
        clock: Clock,
    ) -> None:
        self._ledger = ledger
        self._outcomes = outcomes
        self._labels = labels
        self._clock = clock

    def collect(
        self,
        target: TargetDefinition,
        outcome_cutoff: UtcInstant,
        *,
        prediction_ids: tuple[PredictionId, ...] | None = None,
    ) -> OutcomeCollectionResult:
        selected = (
            tuple(self._ledger.get_prediction(item) for item in prediction_ids)
            if prediction_ids is not None
            else self._ledger.list_predictions(target_key=target.key)
        )
        collected: list[RealizedOutcome] = []
        unchanged: list[PredictionId] = []
        failures: list[OutcomeCollectionFailure] = []
        for prediction in selected:
            if prediction.scope.target_key != target.key:
                failures.append(
                    OutcomeCollectionFailure(
                        prediction.prediction_id,
                        "prediction target does not match collection target",
                    )
                )
                continue
            try:
                label = self._labels.calculate(
                    target,
                    prediction.instrument_id,
                    prediction.as_of,
                    outcome_cutoff,
                )
            except LabelComputationError as exc:
                failures.append(
                    OutcomeCollectionFailure(prediction.prediction_id, str(exc)[:500])
                )
                continue
            if label.value is None:
                failures.append(
                    OutcomeCollectionFailure(
                        prediction.prediction_id,
                        label.missing_reason or "realized label is unavailable",
                    )
                )
                continue
            current = self._outcomes.latest_for_prediction(prediction.prediction_id)
            if current is not None and current.source_label_fingerprint == label.fingerprint:
                unchanged.append(prediction.prediction_id)
                continue
            actual = Decimal(label.value)
            if target.value_type is TargetValueType.BINARY:
                direction_correct = int(prediction.predicted_value >= Decimal("0.5")) == int(
                    actual
                )
            else:
                direction_correct = (prediction.predicted_value > 0) == (actual > 0)
            outcome = RealizedOutcome(
                outcome_id=OutcomeId.new(),
                prediction_id=prediction.prediction_id,
                model_version_id=prediction.model_version_id,
                instrument_id=prediction.instrument_id,
                target_key=target.key,
                as_of=prediction.as_of,
                horizon_end=label.horizon_end,
                observed_at=self._clock.now(),
                source_label_id=label.label_id,
                source_label_fingerprint=label.fingerprint,
                prediction_value=prediction.predicted_value,
                actual_value=actual,
                positive_probability=prediction.positive_probability,
                direction_correct=direction_correct,
                revision=1 if current is None else current.revision + 1,
                supersedes=current.outcome_id if current is not None else None,
            )
            self._outcomes.append(outcome)
            collected.append(outcome)
        return OutcomeCollectionResult(
            collected=tuple(collected),
            unchanged_prediction_ids=tuple(unchanged),
            failures=tuple(failures),
            completed_at=self._clock.now(),
        )


class FeedbackService:
    __slots__ = ("_clock", "_outcomes")

    def __init__(self, outcomes: OutcomeRepository, clock: Clock) -> None:
        self._outcomes = outcomes
        self._clock = clock

    def summarize(
        self,
        model_version_id: ModelVersionId,
        target_key: str,
        window: InstantInterval,
    ) -> FeedbackSummary:
        target = target_key.strip().lower()
        outcomes = tuple(
            item
            for item in self._outcomes.list_latest(model_version_id=model_version_id)
            if item.target_key == target and window.contains(item.observed_at)
        )
        if not outcomes:
            raise FeedbackError("No realized outcomes are available for the feedback window")
        count = Decimal(len(outcomes))
        mae = sum((item.absolute_error for item in outcomes), start=Decimal(0)) / count
        mse = sum((item.squared_error for item in outcomes), start=Decimal(0)) / count
        bias = sum((item.error for item in outcomes), start=Decimal(0)) / count
        with localcontext() as context:
            context.prec = 34
            rmse = mse.sqrt()
        metrics = [
            FeedbackMetric("mae", mae),
            FeedbackMetric("rmse", rmse),
            FeedbackMetric("bias", bias),
        ]
        directional = tuple(
            item.direction_correct
            for item in outcomes
            if item.direction_correct is not None
        )
        if directional:
            accuracy = Decimal(sum(int(item) for item in directional)) / Decimal(
                len(directional)
            )
            metrics.append(FeedbackMetric("directional_accuracy", accuracy))
        probabilistic = tuple(
            item for item in outcomes if item.positive_probability is not None
        )
        if probabilistic:
            brier = sum(
                (
                    (item.positive_probability.value - item.actual_value) ** 2
                    for item in probabilistic
                    if item.positive_probability is not None
                ),
                start=Decimal(0),
            ) / Decimal(len(probabilistic))
            metrics.append(FeedbackMetric("brier_score", brier))
        return FeedbackSummary(
            model_version_id=model_version_id,
            target_key=target,
            window=window,
            sample_count=len(outcomes),
            metrics=tuple(metrics),
            generated_at=self._clock.now(),
            outcome_fingerprints=tuple(item.fingerprint for item in outcomes),
        )
