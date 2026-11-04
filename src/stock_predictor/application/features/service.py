"""Train/serve-consistent point-in-time feature materialization pipeline."""

from __future__ import annotations

from datetime import date

from stock_predictor.application.features.registry import FeatureCalculatorRegistry
from stock_predictor.application.point_in_time.service import PointInTimePriceService
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import (
    FeatureComputationError,
    PointInTimeViolationError,
)
from stock_predictor.domain.common.identifiers import FeatureSnapshotId, InstrumentId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.features import (
    FeatureObservation,
    FeatureSet,
    FeatureSnapshot,
    MissingValuePolicy,
)
from stock_predictor.ports.feature_store import FeatureStore


class FeaturePipeline:
    """Uses one calculation path for historical training and production inference features."""

    __slots__ = ("_calculators", "_clock", "_prices", "_store")

    def __init__(
        self,
        calculators: FeatureCalculatorRegistry,
        prices: PointInTimePriceService,
        store: FeatureStore,
        clock: Clock,
    ) -> None:
        self._calculators = calculators
        self._prices = prices
        self._store = store
        self._clock = clock

    def materialize(
        self,
        feature_set: FeatureSet,
        instrument_id: InstrumentId,
        as_of: date,
        decision_cutoff: UtcInstant,
        *,
        adjusted: bool = True,
    ) -> FeatureSnapshot:
        history = self._prices.feature_history(
            instrument_id,
            as_of,
            decision_cutoff,
            feature_set.maximum_lookback + 1,
            adjusted=adjusted,
        )
        if any(
            item.session_date > as_of or item.available_at > decision_cutoff
            for item in history
        ):
            raise PointInTimeViolationError("Feature inputs violate the decision boundary")
        input_fingerprint = self._prices.input_fingerprint(history)
        cached = self._store.get(
            feature_set.feature_set_version_id,
            instrument_id,
            as_of,
            decision_cutoff,
            input_fingerprint,
        )
        if cached is not None:
            return cached
        observations: list[FeatureObservation] = []
        available_ids = {item.bar_id for item in history}
        for definition in feature_set.definitions:
            calculator = self._calculators.get(definition.key)
            if calculator.definition != definition:
                raise FeatureComputationError(
                    f"Calculator definition differs from feature-set contract: {definition.key}"
                )
            observation = calculator.calculate(history)
            if not set(observation.source_bar_ids).issubset(available_ids):
                raise FeatureComputationError(
                    f"Feature calculator used undeclared source bars: {definition.key}"
                )
            if observation.value is None:
                if definition.missing_value_policy is MissingValuePolicy.FAIL:
                    raise FeatureComputationError(
                        f"Required feature is missing: {definition.key}: "
                        f"{observation.missing_reason}"
                    )
                if definition.missing_value_policy is MissingValuePolicy.IMPUTE_ZERO:
                    observation = FeatureObservation(
                        definition, 0, None, observation.source_bar_ids
                    )
            observations.append(observation)
        generated_at = self._clock.now()
        if generated_at < decision_cutoff:
            raise PointInTimeViolationError(
                "Feature generation clock is earlier than the decision cutoff"
            )
        snapshot = FeatureSnapshot(
            snapshot_id=FeatureSnapshotId.new(),
            feature_set=feature_set,
            instrument_id=instrument_id,
            as_of=as_of,
            decision_cutoff=decision_cutoff,
            generated_at=generated_at,
            observations=tuple(observations),
            input_fingerprint=input_fingerprint,
        )
        self._store.put(snapshot)
        return snapshot

    def materialize_many(
        self,
        feature_set: FeatureSet,
        instrument_ids: tuple[InstrumentId, ...],
        as_of: date,
        decision_cutoff: UtcInstant,
        *,
        adjusted: bool = True,
    ) -> tuple[FeatureSnapshot, ...]:
        return tuple(
            self.materialize(
                feature_set, item, as_of, decision_cutoff, adjusted=adjusted
            )
            for item in instrument_ids
        )
