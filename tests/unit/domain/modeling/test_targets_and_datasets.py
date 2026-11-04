from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    DatasetRowId,
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
from stock_predictor.domain.modeling.datasets import (
    DatasetBuildPoint,
    DatasetBuildPolicy,
    DatasetRow,
    MissingFeatureAction,
    MissingLabelAction,
)
from stock_predictor.domain.modeling.targets import (
    LabelObservation,
    TargetDefinition,
    TargetKind,
    TargetValueType,
)
from tests.helpers.modeling import make_dataset, regression_target


def test_target_definition_is_versioned_and_typed() -> None:
    target = regression_target(5)

    assert target.key == "future_return@1.0.0"
    assert target.value_type is TargetValueType.CONTINUOUS
    assert len(target.fingerprint) == 64

    direction = TargetDefinition(
        TargetDefinitionId.new(),
        "direction",
        "2",
        TargetKind.DIRECTION,
        PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
        positive_threshold="0.01",
    )
    assert direction.value_type is TargetValueType.BINARY
    assert direction.positive_threshold == Decimal("0.01")


def test_target_definition_validates_kind_specific_contracts() -> None:
    with pytest.raises(DomainValidationError, match="Invalid target name"):
        TargetDefinition(
            TargetDefinitionId.new(),
            "Bad Name",
            "1",
            TargetKind.SIMPLE_RETURN,
            PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
        )
    with pytest.raises(DomainValidationError, match="Target version"):
        TargetDefinition(
            TargetDefinitionId.new(),
            "return_1d",
            " ",
            TargetKind.SIMPLE_RETURN,
            PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
        )
    with pytest.raises(DomainValidationError, match="trading-session"):
        TargetDefinition(
            TargetDefinitionId.new(),
            "return_1d",
            "1",
            TargetKind.SIMPLE_RETURN,
            PredictionHorizon(1, HorizonUnit.CALENDAR_DAYS),
        )
    with pytest.raises(DomainValidationError, match="at least two"):
        TargetDefinition(
            TargetDefinitionId.new(),
            "volatility",
            "1",
            TargetKind.REALIZED_VOLATILITY,
            PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
        )
    with pytest.raises(DomainValidationError, match="require a benchmark"):
        TargetDefinition(
            TargetDefinitionId.new(),
            "relative",
            "1",
            TargetKind.RELATIVE_RETURN,
            PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
        )
    with pytest.raises(DomainValidationError, match="only valid"):
        TargetDefinition(
            TargetDefinitionId.new(),
            "return_1d",
            "1",
            TargetKind.SIMPLE_RETURN,
            PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
            benchmark_instrument_id=InstrumentId.new(),
        )
    with pytest.raises(DomainValidationError, match="Annualization"):
        TargetDefinition(
            TargetDefinitionId.new(),
            "return_1d",
            "1",
            TargetKind.SIMPLE_RETURN,
            PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
            annualization_sessions=0,
        )


def test_label_observation_validates_value_shape_and_has_content_fingerprint() -> None:
    target = regression_target()
    instrument_id = InstrumentId.new()
    cutoff = UtcInstant(datetime(2025, 1, 4, 22, tzinfo=UTC))
    available = cutoff.plus(timedelta(minutes=-1))
    bar_id = PriceBarId.new()
    first = LabelObservation(
        LabelId.new(),
        target,
        instrument_id,
        date(2025, 1, 2),
        date(2025, 1, 3),
        cutoff,
        available,
        "0.05",
        None,
        (bar_id,),
    )
    second = LabelObservation(
        LabelId.new(),
        target,
        instrument_id,
        date(2025, 1, 2),
        date(2025, 1, 3),
        cutoff,
        available,
        Decimal("0.05"),
        None,
        (bar_id,),
    )
    assert first.value == Decimal("0.05")
    assert first.fingerprint == second.fingerprint
    assert first.is_missing is False

    missing = LabelObservation(
        LabelId.new(),
        target,
        instrument_id,
        date(2025, 1, 2),
        date(2025, 1, 3),
        cutoff,
        cutoff,
        None,
        "price unavailable",
        (),
    )
    assert missing.is_missing is True


def test_label_observation_rejects_invalid_state() -> None:
    target = regression_target()
    binary = TargetDefinition(
        TargetDefinitionId.new(),
        "direction",
        "1",
        TargetKind.DIRECTION,
        PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
    )
    instrument_id = InstrumentId.new()
    cutoff = UtcInstant(datetime(2025, 1, 4, 22, tzinfo=UTC))
    arguments = (
        LabelId.new(),
        target,
        instrument_id,
        date(2025, 1, 2),
        date(2025, 1, 3),
        cutoff,
        cutoff,
    )
    with pytest.raises(DomainValidationError, match="require a reason"):
        LabelObservation(*arguments, None, None, ())
    with pytest.raises(DomainValidationError, match="cannot carry"):
        LabelObservation(*arguments, "0.1", "unexpected", ())
    with pytest.raises(DomainValidationError, match="0 or 1"):
        LabelObservation(
            LabelId.new(),
            binary,
            instrument_id,
            date(2025, 1, 2),
            date(2025, 1, 3),
            cutoff,
            cutoff,
            2,
            None,
            (),
        )
    with pytest.raises(DomainValidationError, match="later than as-of"):
        LabelObservation(
            LabelId.new(),
            target,
            instrument_id,
            date(2025, 1, 2),
            date(2025, 1, 2),
            cutoff,
            cutoff,
            0,
            None,
            (),
        )
    with pytest.raises(DomainValidationError, match="after its outcome"):
        LabelObservation(
            LabelId.new(),
            target,
            instrument_id,
            date(2025, 1, 2),
            date(2025, 1, 3),
            cutoff,
            cutoff.plus(timedelta(seconds=1)),
            0,
            None,
            (),
        )


def test_dataset_build_point_and_policy_are_strict() -> None:
    instrument_id = InstrumentId.new()
    decision = UtcInstant(datetime(2025, 1, 2, 20, tzinfo=UTC))
    outcome = decision.plus(timedelta(days=2))
    point = DatasetBuildPoint(instrument_id, date(2025, 1, 2), decision, outcome, "2")
    policy = DatasetBuildPolicy(
        missing_feature_action=MissingFeatureAction.IMPUTE_ZERO,
        missing_label_action=MissingLabelAction.FAIL,
    )
    assert point.sample_weight == Decimal(2)
    assert '"impute_zero"' in policy.canonical_json

    with pytest.raises(DomainValidationError, match="later"):
        DatasetBuildPoint(instrument_id, date(2025, 1, 2), decision, decision)
    with pytest.raises(DomainValidationError, match="positive"):
        DatasetBuildPoint(instrument_id, date(2025, 1, 2), decision, outcome, 0)
    with pytest.raises(DomainValidationError, match="version"):
        DatasetBuildPolicy(version=" ")


def test_dataset_snapshot_is_sorted_and_content_addressed() -> None:
    dataset = make_dataset(periods=3, instruments_per_period=2)

    assert dataset.row_count == 6
    assert dataset.feature_keys == ("momentum@1.0.0", "market_return@1.0.0")
    assert tuple(row.as_of for row in dataset.rows) == tuple(
        sorted(row.as_of for row in dataset.rows)
    )
    assert len(dataset.fingerprint) == 64

    replacement = replace(dataset, dataset_version_id=type(dataset.dataset_version_id).new())
    later_publication = replace(
        dataset,
        created_at=dataset.created_at.plus(timedelta(hours=1)),
    )
    assert replacement.fingerprint == dataset.fingerprint
    assert later_publication.fingerprint == dataset.fingerprint

    with pytest.raises(DomainValidationError, match="Feature-set fingerprint"):
        replace(dataset, feature_set_fingerprint="not-a-digest")


def test_dataset_row_rejects_misalignment_and_temporal_leakage() -> None:
    dataset = make_dataset(periods=1)
    row = dataset.rows[0]
    with pytest.raises(DomainValidationError, match="empty or misaligned"):
        replace(row, feature_values=())
    with pytest.raises(DomainValidationError, match="later than as-of"):
        replace(row, label_end_date=row.as_of)
    with pytest.raises(DomainValidationError, match="after the decision"):
        replace(row, label_available_at=row.decision_cutoff)
    with pytest.raises(DomainValidationError, match="positive"):
        replace(row, sample_weight=Decimal(0))
    with pytest.raises(DomainValidationError, match="Source label fingerprint"):
        replace(row, source_label_fingerprint="")
    with pytest.raises(DomainValidationError, match="Source feature fingerprint"):
        replace(row, source_feature_fingerprint="invalid")
