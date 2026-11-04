"""Point-in-time dataset construction with deterministic content fingerprints."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from stock_predictor.application.features.service import FeaturePipeline
from stock_predictor.application.labels.service import TargetLabelService
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import DatasetConstructionError
from stock_predictor.domain.common.identifiers import (
    DatasetRowId,
    DatasetVersionId,
    TargetDefinitionId,
)
from stock_predictor.domain.market_data.features import FeatureSet
from stock_predictor.domain.modeling.datasets import (
    DatasetBuildPoint,
    DatasetBuildPolicy,
    DatasetRow,
    DatasetSnapshot,
    MissingFeatureAction,
    MissingLabelAction,
)
from stock_predictor.domain.modeling.targets import (
    LabelObservation,
    TargetDefinition,
    TargetKind,
)
from stock_predictor.ports.dataset_repository import DatasetRepository


class DatasetBuilder:
    """Builds immutable model-ready rows from the same feature path used for serving."""

    __slots__ = ("_clock", "_features", "_labels", "_repository")

    def __init__(
        self,
        features: FeaturePipeline,
        labels: TargetLabelService,
        repository: DatasetRepository,
        clock: Clock,
    ) -> None:
        self._features = features
        self._labels = labels
        self._repository = repository
        self._clock = clock

    def build(
        self,
        name: str,
        feature_set: FeatureSet,
        target: TargetDefinition,
        points: tuple[DatasetBuildPoint, ...],
        policy: DatasetBuildPolicy = DatasetBuildPolicy(),
    ) -> DatasetSnapshot:
        if not points:
            raise DatasetConstructionError("Dataset build requires at least one point")
        point_keys = tuple((item.instrument_id, item.as_of) for item in points)
        if len(set(point_keys)) != len(point_keys):
            raise DatasetConstructionError(
                "Dataset build points must be unique by instrument and as-of date"
            )
        labels = self._materialize_labels(target, points)
        label_by_key = {(item.instrument_id, item.as_of): item for item in labels}
        rows: list[DatasetRow] = []
        for point in sorted(points, key=lambda item: (item.as_of, str(item.instrument_id))):
            label = label_by_key[(point.instrument_id, point.as_of)]
            if label.is_missing:
                if policy.missing_label_action is MissingLabelAction.FAIL:
                    raise DatasetConstructionError(
                        f"Missing label for {point.instrument_id}/{point.as_of}: "
                        f"{label.missing_reason}"
                    )
                continue
            snapshot = self._features.materialize(
                feature_set,
                point.instrument_id,
                point.as_of,
                point.decision_cutoff,
                adjusted=policy.adjusted_features,
            )
            values: list[Decimal] = []
            drop_row = False
            for observation in snapshot.observations:
                if observation.value is None:
                    if policy.missing_feature_action is MissingFeatureAction.FAIL:
                        raise DatasetConstructionError(
                            f"Missing feature {observation.definition.key} for "
                            f"{point.instrument_id}/{point.as_of}: "
                            f"{observation.missing_reason}"
                        )
                    if policy.missing_feature_action is MissingFeatureAction.DROP_ROW:
                        drop_row = True
                        break
                    values.append(Decimal(0))
                elif isinstance(observation.value, bool):
                    values.append(Decimal(int(observation.value)))
                else:
                    values.append(Decimal(observation.value))
            if drop_row:
                continue
            if label.value is None:  # Defensive: handled above.
                raise DatasetConstructionError("Unexpected missing label")
            rows.append(
                DatasetRow(
                    row_id=DatasetRowId.new(),
                    instrument_id=point.instrument_id,
                    as_of=point.as_of,
                    decision_cutoff=point.decision_cutoff,
                    feature_keys=tuple(item.key for item in feature_set.definitions),
                    feature_values=tuple(values),
                    target_key=target.key,
                    target_value=label.value,
                    label_end_date=label.horizon_end,
                    label_available_at=label.available_at,
                    sample_weight=point.sample_weight,
                    source_feature_snapshot_id=snapshot.snapshot_id,
                    source_label_id=label.label_id,
                    source_feature_fingerprint=snapshot.fingerprint,
                    source_label_fingerprint=label.fingerprint,
                )
            )
        if not rows:
            raise DatasetConstructionError("Dataset policy removed every requested row")
        created_at = self._clock.now()
        if created_at < max(item.outcome_cutoff for item in points):
            raise DatasetConstructionError(
                "Dataset creation clock is earlier than an outcome cutoff"
            )
        candidate = DatasetSnapshot(
            dataset_version_id=DatasetVersionId.new(),
            name=name,
            feature_set_version_id=feature_set.feature_set_version_id,
            feature_set_fingerprint=feature_set.fingerprint,
            target=target,
            rows=tuple(rows),
            created_at=created_at,
            build_policy=policy.canonical_json,
        )
        existing = self._repository.find_by_fingerprint(candidate.fingerprint)
        if existing is not None:
            return existing
        self._repository.put(candidate)
        return candidate

    def _materialize_labels(
        self,
        target: TargetDefinition,
        points: tuple[DatasetBuildPoint, ...],
    ) -> tuple[LabelObservation, ...]:
        if target.kind is not TargetKind.CROSS_SECTIONAL_RANK:
            return tuple(
                self._labels.calculate(
                    target,
                    point.instrument_id,
                    point.as_of,
                    point.outcome_cutoff,
                )
                for point in points
            )
        source_target = TargetDefinition(
            target_definition_id=TargetDefinitionId(
                uuid5(
                    NAMESPACE_URL,
                    f"{target.target_definition_id}:source-simple-return",
                )
            ),
            name=f"{target.name}_source_return",
            version=target.version,
            kind=TargetKind.SIMPLE_RETURN,
            horizon=target.horizon,
        )
        by_date: dict[date, list[tuple[DatasetBuildPoint, LabelObservation]]] = (
            defaultdict(list)
        )
        for point in points:
            source = self._labels.calculate(
                source_target,
                point.instrument_id,
                point.as_of,
                point.outcome_cutoff,
            )
            by_date[point.as_of].append((point, source))
        ranked: list[LabelObservation] = []
        for as_of in sorted(by_date):
            group = tuple(item[1] for item in by_date[as_of])
            ranked.extend(self._labels.rank_cross_section(target, group))
        return tuple(ranked)
