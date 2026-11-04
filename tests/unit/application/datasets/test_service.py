from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stock_predictor.adapters.repositories.in_memory_dataset_repository import (
    InMemoryDatasetRepository,
)
from stock_predictor.application.datasets.service import DatasetBuilder
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import DatasetConstructionError
from stock_predictor.domain.common.identifiers import (
    FeatureSetVersionId,
    FeatureSnapshotId,
    InstrumentId,
    LabelId,
    PriceBarId,
    TargetDefinitionId,
)
from stock_predictor.domain.common.temporal import (
    HorizonUnit,
    PredictionHorizon,
    UtcInstant,
)
from stock_predictor.domain.market_data.features import (
    FeatureDefinition,
    FeatureObservation,
    FeatureSet,
    FeatureSnapshot,
)
from stock_predictor.domain.modeling.datasets import (
    DatasetBuildPoint,
    DatasetBuildPolicy,
    MissingFeatureAction,
    MissingLabelAction,
)
from stock_predictor.domain.modeling.targets import (
    LabelObservation,
    TargetDefinition,
    TargetKind,
)


class FakeFeaturePipeline:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.calls = []

    def materialize(self, feature_set, instrument_id, as_of, decision_cutoff, **kwargs):
        self.calls.append((instrument_id, as_of, kwargs))
        return self.snapshots[(instrument_id, as_of)]


class FakeLabels:
    def __init__(self, labels):
        self.labels = labels
        self.rank_calls = 0

    def calculate(self, target, instrument_id, as_of, outcome_cutoff):
        source = self.labels[(instrument_id, as_of)]
        if source.target.kind is target.kind:
            return source
        return LabelObservation(
            LabelId.new(),
            target,
            instrument_id,
            as_of,
            source.horizon_end,
            outcome_cutoff,
            source.available_at,
            source.value,
            source.missing_reason,
            source.source_bar_ids,
        )

    def rank_cross_section(self, rank_target, labels):
        self.rank_calls += 1
        ordered = sorted(
            (item for item in labels if item.value is not None),
            key=lambda item: Decimal(item.value),
        )
        result = []
        for item in labels:
            value = None if item.value is None else Decimal(ordered.index(item)) / Decimal(
                max(len(ordered) - 1, 1)
            )
            result.append(
                LabelObservation(
                    LabelId.new(),
                    rank_target,
                    item.instrument_id,
                    item.as_of,
                    item.horizon_end,
                    item.outcome_cutoff,
                    item.available_at,
                    value,
                    item.missing_reason if value is None else None,
                    item.source_bar_ids,
                )
            )
        return tuple(result)


def setup_objects(missing_feature=False, missing_label=False):
    definition = FeatureDefinition("momentum", "1", "Momentum", 0, 1)
    feature_set = FeatureSet(
        FeatureSetVersionId.new(),
        "core",
        "1",
        (definition,),
    )
    target = TargetDefinition(
        TargetDefinitionId.new(),
        "future_return",
        "1",
        TargetKind.SIMPLE_RETURN,
        PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
    )
    instrument = InstrumentId.new()
    as_of = date(2025, 1, 2)
    decision = UtcInstant(datetime(2025, 1, 2, 21, tzinfo=UTC))
    outcome = UtcInstant(datetime(2025, 1, 4, 21, tzinfo=UTC))
    observation = FeatureObservation(
        definition,
        None if missing_feature else Decimal("0.2"),
        "missing" if missing_feature else None,
        (PriceBarId.new(),),
    )
    snapshot = FeatureSnapshot(
        FeatureSnapshotId.new(),
        feature_set,
        instrument,
        as_of,
        decision,
        outcome,
        (observation,),
        "a" * 64,
    )
    label = LabelObservation(
        LabelId.new(),
        target,
        instrument,
        as_of,
        date(2025, 1, 3),
        outcome,
        outcome.plus(timedelta(minutes=-1)),
        None if missing_label else Decimal("0.1"),
        "missing outcome" if missing_label else None,
        (PriceBarId.new(),),
    )
    point = DatasetBuildPoint(instrument, as_of, decision, outcome)
    return feature_set, target, point, snapshot, label


def test_dataset_builder_publishes_idempotent_numeric_snapshot() -> None:
    feature_set, target, point, snapshot, label = setup_objects()
    repository = InMemoryDatasetRepository()
    builder = DatasetBuilder(
        FakeFeaturePipeline({(point.instrument_id, point.as_of): snapshot}),
        FakeLabels({(point.instrument_id, point.as_of): label}),
        repository,
        FixedClock(UtcInstant(datetime(2025, 1, 5, tzinfo=UTC))),
    )

    first = builder.build("training", feature_set, target, (point,))
    second = builder.build("training", feature_set, target, (point,))

    assert first is second
    assert first.rows[0].feature_values == (Decimal("0.2"),)
    assert first.rows[0].target_value == Decimal("0.1")
    assert repository.get(first.dataset_version_id) is first


def test_dataset_builder_applies_missing_feature_policies() -> None:
    feature_set, target, point, snapshot, label = setup_objects(missing_feature=True)
    features = FakeFeaturePipeline({(point.instrument_id, point.as_of): snapshot})
    labels = FakeLabels({(point.instrument_id, point.as_of): label})
    clock = FixedClock(UtcInstant(datetime(2025, 1, 5, tzinfo=UTC)))

    with pytest.raises(DatasetConstructionError, match="Missing feature"):
        DatasetBuilder(features, labels, InMemoryDatasetRepository(), clock).build(
            "training",
            feature_set,
            target,
            (point,),
            DatasetBuildPolicy(missing_feature_action=MissingFeatureAction.FAIL),
        )
    with pytest.raises(DatasetConstructionError, match="removed every"):
        DatasetBuilder(features, labels, InMemoryDatasetRepository(), clock).build(
            "training",
            feature_set,
            target,
            (point,),
            DatasetBuildPolicy(missing_feature_action=MissingFeatureAction.DROP_ROW),
        )
    dataset = DatasetBuilder(
        features,
        labels,
        InMemoryDatasetRepository(),
        clock,
    ).build(
        "training",
        feature_set,
        target,
        (point,),
        DatasetBuildPolicy(missing_feature_action=MissingFeatureAction.IMPUTE_ZERO),
    )
    assert dataset.rows[0].feature_values == (Decimal(0),)


def test_dataset_builder_applies_missing_label_policy_and_validates_request() -> None:
    feature_set, target, point, snapshot, label = setup_objects(missing_label=True)
    builder = DatasetBuilder(
        FakeFeaturePipeline({(point.instrument_id, point.as_of): snapshot}),
        FakeLabels({(point.instrument_id, point.as_of): label}),
        InMemoryDatasetRepository(),
        FixedClock(UtcInstant(datetime(2025, 1, 5, tzinfo=UTC))),
    )
    with pytest.raises(DatasetConstructionError, match="Missing label"):
        builder.build(
            "training",
            feature_set,
            target,
            (point,),
            DatasetBuildPolicy(missing_label_action=MissingLabelAction.FAIL),
        )
    with pytest.raises(DatasetConstructionError, match="removed every"):
        builder.build("training", feature_set, target, (point,))
    with pytest.raises(DatasetConstructionError, match="at least one"):
        builder.build("training", feature_set, target, ())
    with pytest.raises(DatasetConstructionError, match="unique"):
        builder.build("training", feature_set, target, (point, point))


def test_dataset_builder_supports_cross_sectional_rank_and_clock_guard() -> None:
    first = setup_objects()
    feature_set, _, point_one, snapshot_one, label_one = first
    _, _, base_point, _, _ = setup_objects()
    instrument_two = InstrumentId.new()
    point_two = DatasetBuildPoint(
        instrument_two,
        point_one.as_of,
        point_one.decision_cutoff,
        point_one.outcome_cutoff,
    )
    snapshot_two = FeatureSnapshot(
        FeatureSnapshotId.new(),
        feature_set,
        instrument_two,
        point_two.as_of,
        point_two.decision_cutoff,
        point_two.outcome_cutoff,
        (
            FeatureObservation(
                feature_set.definitions[0],
                Decimal("0.3"),
                None,
                (PriceBarId.new(),),
            ),
        ),
        "b" * 64,
    )
    source_target = label_one.target
    label_two = LabelObservation(
        LabelId.new(),
        source_target,
        instrument_two,
        point_two.as_of,
        label_one.horizon_end,
        point_two.outcome_cutoff,
        label_one.available_at,
        Decimal("0.2"),
        None,
        (PriceBarId.new(),),
    )
    rank_target = TargetDefinition(
        TargetDefinitionId.new(),
        "return_rank",
        "1",
        TargetKind.CROSS_SECTIONAL_RANK,
        PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
    )
    labels = FakeLabels(
        {
            (point_one.instrument_id, point_one.as_of): label_one,
            (point_two.instrument_id, point_two.as_of): label_two,
        }
    )
    builder = DatasetBuilder(
        FakeFeaturePipeline(
            {
                (point_one.instrument_id, point_one.as_of): snapshot_one,
                (point_two.instrument_id, point_two.as_of): snapshot_two,
            }
        ),
        labels,
        InMemoryDatasetRepository(),
        FixedClock(UtcInstant(datetime(2025, 1, 5, tzinfo=UTC))),
    )
    dataset = builder.build(
        "ranked",
        feature_set,
        rank_target,
        (point_one, point_two),
    )
    assert labels.rank_calls == 1
    assert {row.target_value for row in dataset.rows} == {Decimal(0), Decimal(1)}

    early_builder = DatasetBuilder(
        FakeFeaturePipeline({(point_one.instrument_id, point_one.as_of): snapshot_one}),
        FakeLabels({(point_one.instrument_id, point_one.as_of): label_one}),
        InMemoryDatasetRepository(),
        FixedClock(point_one.decision_cutoff),
    )
    with pytest.raises(DatasetConstructionError, match="earlier than an outcome"):
        early_builder.build("early", feature_set, source_target, (point_one,))
