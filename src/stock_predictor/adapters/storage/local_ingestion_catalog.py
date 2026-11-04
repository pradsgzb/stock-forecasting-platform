"""Durable JSON catalog for immutable ingestion manifests and resumable checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from threading import RLock
from typing import Any

from stock_predictor.domain.common.errors import ImmutableObjectConflictError
from stock_predictor.domain.common.identifiers import IngestionRunId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market_data.contracts import (
    BarFrequency,
    PriceAdjustment,
    PriceBarRequest,
)
from stock_predictor.domain.market_data.ingestion import (
    IngestionCheckpoint,
    IngestionManifest,
    IngestionPageManifest,
    IngestionStatus,
    RawObjectDescriptor,
    Sha256Digest,
)

_SCHEMA = "stock-predictor.ingestion-catalog.v1"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _safe_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_to_dict(request: PriceBarRequest) -> dict[str, object]:
    return {
        "provider": str(request.provider),
        "exchange_mic": str(request.exchange_mic),
        "symbols": [str(item) for item in request.symbols],
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "frequency": request.frequency.value,
        "adjustment": request.adjustment.value,
        "page_size": request.page_size,
        "request_fingerprint": request.request_fingerprint,
    }


def _request_from_dict(value: dict[str, Any]) -> PriceBarRequest:
    request = PriceBarRequest(
        provider=ProviderName(value["provider"]),
        exchange_mic=MarketIdentifierCode(value["exchange_mic"]),
        symbols=tuple(TickerSymbol(item) for item in value["symbols"]),
        start=date.fromisoformat(value["start"]),
        end=date.fromisoformat(value["end"]),
        frequency=BarFrequency(value["frequency"]),
        adjustment=PriceAdjustment(value["adjustment"]),
        page_size=int(value["page_size"]),
    )
    if request.request_fingerprint != value["request_fingerprint"]:
        raise ImmutableObjectConflictError("Catalog request fingerprint is invalid")
    return request


def _page_to_dict(page: IngestionPageManifest) -> dict[str, object]:
    return {
        "page_number": page.page_number,
        "cursor_in": page.cursor_in,
        "cursor_out": page.cursor_out,
        "provider_request_id": page.provider_request_id,
        "schema_version": page.schema_version,
        "content_type": page.content_type,
        "advertised_record_count": page.advertised_record_count,
        "raw_object": {
            "digest": str(page.raw_object.digest),
            "storage_key": page.raw_object.storage_key,
            "byte_count": page.raw_object.byte_count,
        },
        "retrieved_at": page.retrieved_at.isoformat(),
    }


def _page_from_dict(value: dict[str, Any]) -> IngestionPageManifest:
    raw = value["raw_object"]
    return IngestionPageManifest(
        page_number=int(value["page_number"]),
        cursor_in=value["cursor_in"],
        cursor_out=value["cursor_out"],
        provider_request_id=value["provider_request_id"],
        schema_version=value["schema_version"],
        content_type=value["content_type"],
        advertised_record_count=value["advertised_record_count"],
        raw_object=RawObjectDescriptor(
            digest=Sha256Digest(raw["digest"]),
            storage_key=raw["storage_key"],
            byte_count=int(raw["byte_count"]),
        ),
        retrieved_at=UtcInstant.parse(value["retrieved_at"]),
    )


def _manifest_to_dict(manifest: IngestionManifest) -> dict[str, object]:
    return {
        "schema": _SCHEMA,
        "kind": "manifest",
        "run_id": str(manifest.run_id),
        "idempotency_key": manifest.idempotency_key,
        "provider": str(manifest.provider),
        "request": _request_to_dict(manifest.request),
        "started_at": manifest.started_at.isoformat(),
        "completed_at": manifest.completed_at.isoformat(),
        "status": manifest.status.value,
        "pages": [_page_to_dict(item) for item in manifest.pages],
        "failure_reason": manifest.failure_reason,
        "manifest_fingerprint": manifest.manifest_fingerprint,
    }


def _manifest_from_dict(value: dict[str, Any]) -> IngestionManifest:
    if value.get("schema") != _SCHEMA or value.get("kind") != "manifest":
        raise ImmutableObjectConflictError("Unsupported ingestion manifest schema")
    manifest = IngestionManifest(
        run_id=IngestionRunId.parse(value["run_id"]),
        idempotency_key=value["idempotency_key"],
        provider=ProviderName(value["provider"]),
        request=_request_from_dict(value["request"]),
        started_at=UtcInstant.parse(value["started_at"]),
        completed_at=UtcInstant.parse(value["completed_at"]),
        status=IngestionStatus(value["status"]),
        pages=tuple(_page_from_dict(item) for item in value["pages"]),
        failure_reason=value["failure_reason"],
    )
    if manifest.manifest_fingerprint != value["manifest_fingerprint"]:
        raise ImmutableObjectConflictError("Ingestion manifest fingerprint is invalid")
    return manifest


def _checkpoint_to_dict(checkpoint: IngestionCheckpoint) -> dict[str, object]:
    return {
        "schema": _SCHEMA,
        "kind": "checkpoint",
        "run_id": str(checkpoint.run_id),
        "idempotency_key": checkpoint.idempotency_key,
        "request_fingerprint": checkpoint.request_fingerprint,
        "next_page_number": checkpoint.next_page_number,
        "next_cursor": checkpoint.next_cursor,
        "completed_pages": [_page_to_dict(item) for item in checkpoint.completed_pages],
        "started_at": checkpoint.started_at.isoformat(),
        "updated_at": checkpoint.updated_at.isoformat(),
    }


def _checkpoint_from_dict(value: dict[str, Any]) -> IngestionCheckpoint:
    if value.get("schema") != _SCHEMA or value.get("kind") != "checkpoint":
        raise ImmutableObjectConflictError("Unsupported ingestion checkpoint schema")
    return IngestionCheckpoint(
        run_id=IngestionRunId.parse(value["run_id"]),
        idempotency_key=value["idempotency_key"],
        request_fingerprint=value["request_fingerprint"],
        next_page_number=int(value["next_page_number"]),
        next_cursor=value["next_cursor"],
        completed_pages=tuple(_page_from_dict(item) for item in value["completed_pages"]),
        started_at=UtcInstant.parse(value["started_at"]),
        updated_at=UtcInstant.parse(value["updated_at"]),
    )


class LocalIngestionCatalog:
    """File-backed catalog suitable for local operation and deterministic integration tests."""

    __slots__ = ("_checkpoints", "_completed", "_lock", "_runs")

    def __init__(self, root: Path) -> None:
        resolved = root.expanduser().resolve()
        self._runs = resolved / "runs"
        self._completed = resolved / "completed"
        self._checkpoints = resolved / "checkpoints"
        for directory in (self._runs, self._completed, self._checkpoints):
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImmutableObjectConflictError(f"Catalog record is unreadable: {path}") from exc
        if not isinstance(value, dict):
            raise ImmutableObjectConflictError("Catalog record root must be an object")
        return value

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _atomic_replace(path: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            LocalIngestionCatalog._sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_once(path: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise ImmutableObjectConflictError(
                        "Immutable catalog record already exists with different content: "
                        f"{path}"
                    )
            except OSError as exc:
                raise ImmutableObjectConflictError(
                    "Atomic publication is unavailable for immutable catalog records"
                ) from exc
            LocalIngestionCatalog._sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def find_completed(self, idempotency_key: str) -> IngestionManifest | None:
        path = self._completed / f"{_safe_key(idempotency_key)}.json"
        if not path.exists():
            return None
        manifest = _manifest_from_dict(self._read(path))
        if manifest.idempotency_key != idempotency_key:
            raise ImmutableObjectConflictError("Ingestion idempotency index collision")
        return manifest

    def save_manifest(self, manifest: IngestionManifest) -> None:
        payload = _canonical_json(_manifest_to_dict(manifest))
        with self._lock:
            self._write_once(self._runs / f"{manifest.run_id}.json", payload)
            if manifest.status is IngestionStatus.COMPLETED:
                self._write_once(
                    self._completed / f"{_safe_key(manifest.idempotency_key)}.json", payload
                )

    def load_checkpoint(self, idempotency_key: str) -> IngestionCheckpoint | None:
        path = self._checkpoints / f"{_safe_key(idempotency_key)}.json"
        if not path.exists():
            return None
        checkpoint = _checkpoint_from_dict(self._read(path))
        if checkpoint.idempotency_key != idempotency_key:
            raise ImmutableObjectConflictError("Ingestion checkpoint index collision")
        return checkpoint

    def save_checkpoint(self, checkpoint: IngestionCheckpoint) -> None:
        path = self._checkpoints / f"{_safe_key(checkpoint.idempotency_key)}.json"
        with self._lock:
            if path.exists():
                existing = _checkpoint_from_dict(self._read(path))
                if (
                    existing.run_id != checkpoint.run_id
                    or existing.idempotency_key != checkpoint.idempotency_key
                    or existing.request_fingerprint != checkpoint.request_fingerprint
                ):
                    raise ImmutableObjectConflictError(
                        "Checkpoint identity cannot change during an ingestion run"
                    )
                if checkpoint.updated_at < existing.updated_at:
                    raise ImmutableObjectConflictError(
                        "Checkpoint update cannot move backward in time"
                    )
                prefix_length = len(existing.completed_pages)
                if checkpoint.completed_pages[:prefix_length] != existing.completed_pages:
                    raise ImmutableObjectConflictError(
                        "Checkpoint update cannot rewrite completed pages"
                    )
            self._atomic_replace(path, _canonical_json(_checkpoint_to_dict(checkpoint)))

    def clear_checkpoint(self, idempotency_key: str) -> None:
        with self._lock:
            (self._checkpoints / f"{_safe_key(idempotency_key)}.json").unlink(
                missing_ok=True
            )
