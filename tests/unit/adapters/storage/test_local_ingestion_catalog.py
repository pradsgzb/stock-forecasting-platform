from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from stock_predictor.adapters.storage.local_ingestion_catalog import LocalIngestionCatalog
from stock_predictor.domain.common.errors import ImmutableObjectConflictError
from stock_predictor.domain.common.identifiers import IngestionRunId
from stock_predictor.domain.market.identifiers import TickerSymbol
from stock_predictor.domain.market_data.contracts import PriceBarRequest
from stock_predictor.domain.market_data.ingestion import (
    IngestionCheckpoint,
    IngestionManifest,
    IngestionPageManifest,
    IngestionStatus,
    RawObjectDescriptor,
    Sha256Digest,
)


def _page(fixed_instant) -> IngestionPageManifest:
    return IngestionPageManifest(
        1,
        None,
        None,
        "provider-request",
        "schema-v1",
        "application/json",
        1,
        RawObjectDescriptor(
            Sha256Digest("b" * 64),
            f"raw/sha256/bb/bb/{'b' * 64}.blob",
            10,
        ),
        fixed_instant,
    )


def _manifest(fixed_instant, synthetic_provider_name, xnys) -> IngestionManifest:
    request = PriceBarRequest(
        synthetic_provider_name,
        xnys,
        (TickerSymbol("AAA"),),
        date(2025, 1, 1),
        date(2025, 1, 2),
    )
    return IngestionManifest(
        IngestionRunId.new(),
        "idempotency",
        synthetic_provider_name,
        request,
        fixed_instant,
        fixed_instant,
        IngestionStatus.COMPLETED,
        (_page(fixed_instant),),
    )


def test_catalog_round_trips_manifest_and_checkpoint(
    tmp_path: Path, fixed_instant, synthetic_provider_name, xnys
) -> None:
    catalog = LocalIngestionCatalog(tmp_path)
    manifest = _manifest(fixed_instant, synthetic_provider_name, xnys)
    checkpoint = IngestionCheckpoint(
        manifest.run_id,
        manifest.idempotency_key,
        manifest.request.request_fingerprint,
        2,
        None,
        manifest.pages,
        fixed_instant,
        fixed_instant,
    )

    catalog.save_checkpoint(checkpoint)
    assert catalog.load_checkpoint("idempotency") == checkpoint
    catalog.save_manifest(manifest)
    assert catalog.find_completed("idempotency") == manifest
    catalog.clear_checkpoint("idempotency")
    assert catalog.load_checkpoint("idempotency") is None


def test_catalog_immutable_manifest_is_idempotent(
    tmp_path: Path, fixed_instant, synthetic_provider_name, xnys
) -> None:
    catalog = LocalIngestionCatalog(tmp_path)
    manifest = _manifest(fixed_instant, synthetic_provider_name, xnys)
    catalog.save_manifest(manifest)
    catalog.save_manifest(manifest)

    run_path = tmp_path / "runs" / f"{manifest.run_id}.json"
    run_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ImmutableObjectConflictError, match="different content"):
        catalog.save_manifest(manifest)


def test_catalog_detects_corrupt_completed_index(
    tmp_path: Path, fixed_instant, synthetic_provider_name, xnys
) -> None:
    catalog = LocalIngestionCatalog(tmp_path)
    manifest = _manifest(fixed_instant, synthetic_provider_name, xnys)
    catalog.save_manifest(manifest)
    completed = next((tmp_path / "completed").iterdir())
    completed.write_text("not-json", encoding="utf-8")

    with pytest.raises(ImmutableObjectConflictError, match="unreadable"):
        catalog.find_completed("idempotency")


def test_catalog_rejects_checkpoint_identity_change(
    tmp_path: Path, fixed_instant, synthetic_provider_name, xnys
) -> None:
    catalog = LocalIngestionCatalog(tmp_path)
    manifest = _manifest(fixed_instant, synthetic_provider_name, xnys)
    checkpoint = IngestionCheckpoint(
        manifest.run_id,
        manifest.idempotency_key,
        manifest.request.request_fingerprint,
        2,
        None,
        manifest.pages,
        fixed_instant,
        fixed_instant,
    )
    catalog.save_checkpoint(checkpoint)

    with pytest.raises(ImmutableObjectConflictError, match="identity"):
        catalog.save_checkpoint(replace(checkpoint, run_id=IngestionRunId.new()))
