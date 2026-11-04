from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from stock_predictor.domain.common.identifiers import (
    DatasetRowId,
    DatasetVersionId,
    FeatureSetVersionId,
    FeatureSnapshotId,
    InstrumentId,
    LabelId,
    ModelVersionId,
    TargetDefinitionId,
)
from stock_predictor.domain.common.temporal import (
    HorizonUnit,
    PredictionHorizon,
    UtcInstant,
)
from stock_predictor.domain.modeling.datasets import DatasetRow, DatasetSnapshot
from stock_predictor.domain.modeling.models import LearningTask, ModelSignature
from stock_predictor.domain.modeling.targets import TargetDefinition, TargetKind


def instant(day: int = 1, hour: int = 20) -> UtcInstant:
    return UtcInstant(datetime(2026, 1, day, hour, tzinfo=UTC))


def regression_target(horizon: int = 1) -> TargetDefinition:
    return TargetDefinition(
        TargetDefinitionId.new(),
        "future_return",
        "1.0.0",
        TargetKind.SIMPLE_RETURN,
        PredictionHorizon(horizon, HorizonUnit.TRADING_SESSIONS),
    )


def classification_target(horizon: int = 1) -> TargetDefinition:
    return TargetDefinition(
        TargetDefinitionId.new(),
        "positive_return",
        "1.0.0",
        TargetKind.DIRECTION,
        PredictionHorizon(horizon, HorizonUnit.TRADING_SESSIONS),
    )


def make_dataset(
    *,
    periods: int = 20,
    instruments_per_period: int = 1,
    classification: bool = False,
    label_horizon_days: int = 1,
) -> DatasetSnapshot:
    target = classification_target() if classification else regression_target()
    instrument_ids = tuple(InstrumentId.new() for _ in range(instruments_per_period))
    rows: list[DatasetRow] = []
    start = date(2025, 1, 2)
    for period in range(periods):
        as_of = start + timedelta(days=period)
        for instrument_index, instrument_id in enumerate(instrument_ids):
            feature_one = Decimal(period + instrument_index + 1) / Decimal(100)
            feature_two = Decimal((period % 5) - 2) / Decimal(10)
            target_value: Decimal | int
            if classification:
                target_value = int((period + instrument_index) % 2 == 0)
            else:
                target_value = feature_one * Decimal("0.5") + feature_two
            rows.append(
                DatasetRow(
                    row_id=DatasetRowId.new(),
                    instrument_id=instrument_id,
                    as_of=as_of,
                    decision_cutoff=UtcInstant(
                        datetime.combine(as_of, datetime.min.time(), tzinfo=UTC)
                        + timedelta(hours=20)
                    ),
                    feature_keys=("momentum@1.0.0", "market_return@1.0.0"),
                    feature_values=(feature_one, feature_two),
                    target_key=target.key,
                    target_value=target_value,
                    label_end_date=as_of + timedelta(days=label_horizon_days),
                    label_available_at=UtcInstant(
                        datetime.combine(
                            as_of + timedelta(days=label_horizon_days),
                            datetime.min.time(),
                            tzinfo=UTC,
                        )
                        + timedelta(hours=21)
                    ),
                    sample_weight=Decimal(1),
                    source_feature_snapshot_id=FeatureSnapshotId.new(),
                    source_label_id=LabelId.new(),
                    source_feature_fingerprint=f"{period:064x}"[-64:],
                    source_label_fingerprint=f"{period + 1:064x}"[-64:],
                )
            )
    return DatasetSnapshot(
        dataset_version_id=DatasetVersionId.new(),
        name="test-dataset",
        feature_set_version_id=FeatureSetVersionId.new(),
        feature_set_fingerprint="a" * 64,
        target=target,
        rows=tuple(rows),
        created_at=instant(31, 23),
        build_policy='{"version":"test"}',
    )


def signature(classification: bool = False) -> ModelSignature:
    return ModelSignature(
        feature_keys=("momentum@1.0.0", "market_return@1.0.0"),
        target_key="positive_return@1.0.0" if classification else "future_return@1.0.0",
        task=(
            LearningTask.BINARY_CLASSIFICATION
            if classification
            else LearningTask.REGRESSION
        ),
    )


def model_version() -> ModelVersionId:
    return ModelVersionId.new()
