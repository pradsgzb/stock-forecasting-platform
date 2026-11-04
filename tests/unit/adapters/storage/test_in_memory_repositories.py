from datetime import date

import pytest

from stock_predictor.adapters.repositories.in_memory_feature_store import InMemoryFeatureStore
from stock_predictor.adapters.repositories.in_memory_ingestion_catalog import (
    InMemoryIngestionCatalog,
)
from stock_predictor.adapters.repositories.in_memory_validation_repository import (
    InMemoryValidationReportRepository,
)
from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.common.identifiers import (
    FeatureSetVersionId,
    FeatureSnapshotId,
    IngestionRunId,
    InstrumentId,
    ValidationReportId,
)
from stock_predictor.domain.market_data.features import (
    FeatureDefinition,
    FeatureObservation,
    FeatureSet,
    FeatureSnapshot,
)
from stock_predictor.domain.market_data.quality import (
    QualityScore,
    ReconciliationReport,
    ValidationReport,
    ValidationStatus,
)


def test_in_memory_validation_repository_returns_latest(fixed_instant) -> None:
    repository = InMemoryValidationReportRepository()
    run_id = IngestionRunId.new()
    first = ValidationReport(
        ValidationReportId.new(),
        run_id,
        fixed_instant,
        ValidationStatus.PASSED,
        QualityScore(100),
        0,
        (),
        ReconciliationReport(None, 0, 1, True),
        "v1",
    )
    repository.add(first)
    repository.add(first)
    assert repository.latest_for_run(run_id) == first


def test_feature_store_is_idempotent_and_conflict_safe(fixed_instant) -> None:
    store = InMemoryFeatureStore()
    definition = FeatureDefinition("close_price", "1", "Close", 0, 1)
    feature_set = FeatureSet(FeatureSetVersionId.new(), "Basic", "1", (definition,))
    instrument_id = InstrumentId.new()
    snapshot = FeatureSnapshot(
        FeatureSnapshotId.new(),
        feature_set,
        instrument_id,
        date(2026, 1, 2),
        fixed_instant,
        fixed_instant,
        (FeatureObservation(definition, "1", None, ()),),
        "a" * 64,
    )
    store.put(snapshot)
    store.put(snapshot)
    assert (
        store.get(
            feature_set.feature_set_version_id,
            instrument_id,
            date(2026, 1, 2),
            fixed_instant,
            "a" * 64,
        )
        == snapshot
    )
    conflicting = FeatureSnapshot(
        FeatureSnapshotId.new(),
        feature_set,
        instrument_id,
        date(2026, 1, 2),
        fixed_instant,
        fixed_instant,
        (FeatureObservation(definition, "2", None, ()),),
        "a" * 64,
    )
    with pytest.raises(DomainConflictError):
        store.put(conflicting)


def test_in_memory_ingestion_catalog_rejects_run_identity_change(fixed_instant) -> None:
    catalog = InMemoryIngestionCatalog()
    from stock_predictor.domain.market_data.ingestion import IngestionCheckpoint

    first = IngestionCheckpoint(
        IngestionRunId.new(), "key", "a" * 64, 1, None, (), fixed_instant, fixed_instant
    )
    second = IngestionCheckpoint(
        IngestionRunId.new(), "key", "a" * 64, 1, None, (), fixed_instant, fixed_instant
    )
    catalog.save_checkpoint(first)
    with pytest.raises(DomainConflictError, match="identity"):
        catalog.save_checkpoint(second)
