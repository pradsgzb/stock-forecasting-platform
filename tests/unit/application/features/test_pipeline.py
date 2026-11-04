from datetime import date, timedelta
from decimal import Decimal
from typing import cast

import pytest

from stock_predictor.adapters.repositories.in_memory_feature_store import InMemoryFeatureStore
from stock_predictor.application.features.calculators import ClosePriceCalculator
from stock_predictor.application.features.registry import FeatureCalculatorRegistry
from stock_predictor.application.features.service import FeaturePipeline
from stock_predictor.application.point_in_time.service import PointInTimePriceService
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    FeatureComputationError,
    PointInTimeViolationError,
)
from stock_predictor.domain.common.identifiers import (
    FeatureSetVersionId,
    InstrumentId,
    PriceBarId,
)
from stock_predictor.domain.market_data.features import (
    FeatureDefinition,
    FeatureInputBar,
    FeatureObservation,
    FeatureSet,
    MissingValuePolicy,
)


def _history(fixed_instant):
    return (
        FeatureInputBar(
            PriceBarId.new(),
            date(2025, 7, 1),
            Decimal("99"),
            Decimal("101"),
            Decimal("98"),
            Decimal("100"),
            Decimal("1000"),
            fixed_instant,
            "a" * 64,
        ),
    )


class StubPrices:
    def __init__(self, history):
        self.history = history
        self.calls = 0

    def feature_history(self, *args, **kwargs):
        self.calls += 1
        return self.history

    @staticmethod
    def input_fingerprint(history):
        return PointInTimePriceService.input_fingerprint(history)


class StaticCalculator:
    def __init__(self, definition, observation):
        self._definition = definition
        self._observation = observation

    @property
    def definition(self):
        return self._definition

    def calculate(self, history):
        return self._observation


def _pipeline(calculators, prices, fixed_instant, store=None):
    return FeaturePipeline(
        FeatureCalculatorRegistry(tuple(calculators)),
        cast(PointInTimePriceService, prices),
        store or InMemoryFeatureStore(),
        FixedClock(fixed_instant),
    )


def test_feature_registry_is_ordered_and_conflict_safe() -> None:
    close = ClosePriceCalculator()
    registry = FeatureCalculatorRegistry((close,))
    assert registry.get(close.definition.key) is close
    assert registry.all() == (close,)
    with pytest.raises(DomainConflictError, match="already registered"):
        registry.register(close)
    with pytest.raises(DomainNotFoundError, match="not registered"):
        registry.get("missing@1")


def test_pipeline_materializes_caches_and_materializes_many(fixed_instant) -> None:
    history = _history(fixed_instant)
    prices = StubPrices(history)
    calculator = ClosePriceCalculator()
    feature_set = FeatureSet(
        FeatureSetVersionId.new(), "Core", "1", (calculator.definition,)
    )
    store = InMemoryFeatureStore()
    pipeline = _pipeline((calculator,), prices, fixed_instant, store)
    instrument_id = InstrumentId.new()

    first = pipeline.materialize(
        feature_set, instrument_id, date(2025, 7, 1), fixed_instant
    )
    second = pipeline.materialize(
        feature_set, instrument_id, date(2025, 7, 1), fixed_instant
    )
    many = pipeline.materialize_many(
        feature_set,
        (instrument_id, InstrumentId.new()),
        date(2025, 7, 1),
        fixed_instant,
    )

    assert first == second
    assert first.observations[0].value == Decimal("100")
    assert len(many) == 2
    assert prices.calls == 4


def test_pipeline_applies_missing_value_policies(fixed_instant) -> None:
    history = _history(fixed_instant)
    definition = FeatureDefinition(
        "optional_value",
        "1",
        "Optional",
        0,
        1,
        missing_value_policy=MissingValuePolicy.RETURN_MISSING,
    )
    missing = FeatureObservation(definition, None, "not available", ())
    pipeline = _pipeline(
        (StaticCalculator(definition, missing),), StubPrices(history), fixed_instant
    )
    feature_set = FeatureSet(FeatureSetVersionId.new(), "Optional", "1", (definition,))
    snapshot = pipeline.materialize(
        feature_set, InstrumentId.new(), date(2025, 7, 1), fixed_instant
    )
    assert snapshot.observations[0].value is None

    fail_definition = FeatureDefinition(
        "required_value",
        "1",
        "Required",
        0,
        1,
        missing_value_policy=MissingValuePolicy.FAIL,
    )
    fail_pipeline = _pipeline(
        (
            StaticCalculator(
                fail_definition,
                FeatureObservation(fail_definition, None, "missing", ()),
            ),
        ),
        StubPrices(history),
        fixed_instant,
    )
    with pytest.raises(FeatureComputationError, match="Required feature"):
        fail_pipeline.materialize(
            FeatureSet(FeatureSetVersionId.new(), "Fail", "1", (fail_definition,)),
            InstrumentId.new(),
            date(2025, 7, 1),
            fixed_instant,
        )

    zero_definition = FeatureDefinition(
        "zero_value",
        "1",
        "Zero",
        0,
        1,
        missing_value_policy=MissingValuePolicy.IMPUTE_ZERO,
    )
    zero_pipeline = _pipeline(
        (
            StaticCalculator(
                zero_definition,
                FeatureObservation(zero_definition, None, "missing", ()),
            ),
        ),
        StubPrices(history),
        fixed_instant,
    )
    zero = zero_pipeline.materialize(
        FeatureSet(FeatureSetVersionId.new(), "Zero", "1", (zero_definition,)),
        InstrumentId.new(),
        date(2025, 7, 1),
        fixed_instant,
    )
    assert zero.observations[0].value == Decimal(0)


def test_pipeline_rejects_contract_mismatch_and_undeclared_source(fixed_instant) -> None:
    history = _history(fixed_instant)
    expected = FeatureDefinition("expected_value", "1", "Expected", 0, 1)
    other = FeatureDefinition("other_value", "1", "Other", 0, 1)
    class MismatchRegistry:
        @staticmethod
        def get(key):
            assert key == expected.key
            return StaticCalculator(other, FeatureObservation(other, 1, None, ()))

    mismatch = FeaturePipeline(
        cast(FeatureCalculatorRegistry, MismatchRegistry()),
        cast(PointInTimePriceService, StubPrices(history)),
        InMemoryFeatureStore(),
        FixedClock(fixed_instant),
    )
    feature_set = FeatureSet(FeatureSetVersionId.new(), "Mismatch", "1", (expected,))
    with pytest.raises(FeatureComputationError, match="differs"):
        mismatch.materialize(
            feature_set, InstrumentId.new(), date(2025, 7, 1), fixed_instant
        )

    rogue = PriceBarId.new()
    calculator = StaticCalculator(
        expected, FeatureObservation(expected, 1, None, (rogue,))
    )
    with pytest.raises(FeatureComputationError, match="undeclared source"):
        _pipeline((calculator,), StubPrices(history), fixed_instant).materialize(
            feature_set, InstrumentId.new(), date(2025, 7, 1), fixed_instant
        )


def test_pipeline_rejects_future_inputs_and_clock_before_cutoff(fixed_instant) -> None:
    calculator = ClosePriceCalculator()
    feature_set = FeatureSet(
        FeatureSetVersionId.new(), "Core", "1", (calculator.definition,)
    )
    future = FeatureInputBar(
        PriceBarId.new(),
        date(2025, 7, 2),
        Decimal("99"),
        Decimal("101"),
        Decimal("98"),
        Decimal("100"),
        Decimal("1000"),
        fixed_instant.plus(timedelta(seconds=1)),
        "a" * 64,
    )
    with pytest.raises(PointInTimeViolationError, match="decision boundary"):
        _pipeline((calculator,), StubPrices((future,)), fixed_instant).materialize(
            feature_set, InstrumentId.new(), date(2025, 7, 1), fixed_instant
        )

    cutoff = fixed_instant.plus(timedelta(seconds=1))
    with pytest.raises(PointInTimeViolationError, match="earlier"):
        _pipeline((calculator,), StubPrices(_history(fixed_instant)), fixed_instant).materialize(
            feature_set, InstrumentId.new(), date(2025, 7, 1), cutoff
        )
