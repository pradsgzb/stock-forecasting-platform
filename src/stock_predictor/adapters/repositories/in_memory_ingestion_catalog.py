"""Thread-safe in-memory ingestion catalog for tests and ephemeral processes."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.market_data.ingestion import (
    IngestionCheckpoint,
    IngestionManifest,
    IngestionStatus,
)


class InMemoryIngestionCatalog:
    __slots__ = ("_checkpoints", "_completed", "_lock", "_runs")

    def __init__(self) -> None:
        self._runs: dict[str, IngestionManifest] = {}
        self._completed: dict[str, IngestionManifest] = {}
        self._checkpoints: dict[str, IngestionCheckpoint] = {}
        self._lock = RLock()

    def find_completed(self, idempotency_key: str) -> IngestionManifest | None:
        with self._lock:
            return self._completed.get(idempotency_key)

    def save_manifest(self, manifest: IngestionManifest) -> None:
        with self._lock:
            key = str(manifest.run_id)
            existing = self._runs.get(key)
            if existing is not None and existing != manifest:
                raise DomainConflictError("Ingestion run already has a different manifest")
            self._runs[key] = manifest
            if manifest.status is IngestionStatus.COMPLETED:
                completed = self._completed.get(manifest.idempotency_key)
                if completed is not None and completed != manifest:
                    raise DomainConflictError("Idempotency key already has a completed manifest")
                self._completed[manifest.idempotency_key] = manifest

    def load_checkpoint(self, idempotency_key: str) -> IngestionCheckpoint | None:
        with self._lock:
            return self._checkpoints.get(idempotency_key)

    def save_checkpoint(self, checkpoint: IngestionCheckpoint) -> None:
        with self._lock:
            existing = self._checkpoints.get(checkpoint.idempotency_key)
            if existing is not None and existing.run_id != checkpoint.run_id:
                raise DomainConflictError("Checkpoint run identity cannot change")
            self._checkpoints[checkpoint.idempotency_key] = checkpoint

    def clear_checkpoint(self, idempotency_key: str) -> None:
        with self._lock:
            self._checkpoints.pop(idempotency_key, None)
