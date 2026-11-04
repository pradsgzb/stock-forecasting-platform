"""Port for ingestion manifests and resumable checkpoints."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.market_data.ingestion import (
    IngestionCheckpoint,
    IngestionManifest,
)


@runtime_checkable
class IngestionCatalog(Protocol):
    """Stores immutable terminal manifests and replaceable operational checkpoints."""

    def find_completed(self, idempotency_key: str) -> IngestionManifest | None:
        ...

    def save_manifest(self, manifest: IngestionManifest) -> None:
        ...

    def load_checkpoint(self, idempotency_key: str) -> IngestionCheckpoint | None:
        ...

    def save_checkpoint(self, checkpoint: IngestionCheckpoint) -> None:
        ...

    def clear_checkpoint(self, idempotency_key: str) -> None:
        ...
