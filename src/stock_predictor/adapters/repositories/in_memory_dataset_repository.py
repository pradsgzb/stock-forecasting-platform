"""Thread-safe in-memory immutable dataset repository."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.common.errors import DomainConflictError, DomainNotFoundError
from stock_predictor.domain.common.identifiers import DatasetVersionId
from stock_predictor.domain.modeling.datasets import DatasetSnapshot


class InMemoryDatasetRepository:
    __slots__ = ("_by_fingerprint", "_by_id", "_lock")

    def __init__(self) -> None:
        self._by_id: dict[DatasetVersionId, DatasetSnapshot] = {}
        self._by_fingerprint: dict[str, DatasetSnapshot] = {}
        self._lock = RLock()

    def put(self, dataset: DatasetSnapshot) -> None:
        with self._lock:
            existing_id = self._by_id.get(dataset.dataset_version_id)
            if existing_id is not None and existing_id != dataset:
                raise DomainConflictError(
                    f"Dataset version is immutable: {dataset.dataset_version_id}"
                )
            existing_fingerprint = self._by_fingerprint.get(dataset.fingerprint)
            if existing_fingerprint is not None and existing_fingerprint != dataset:
                # Equivalent content with a different generated ID is idempotent. The caller
                # should use find_by_fingerprint before publication when stable identity matters.
                return
            self._by_id[dataset.dataset_version_id] = dataset
            self._by_fingerprint[dataset.fingerprint] = dataset

    def get(self, dataset_version_id: DatasetVersionId) -> DatasetSnapshot:
        with self._lock:
            try:
                return self._by_id[dataset_version_id]
            except KeyError as exc:
                raise DomainNotFoundError(
                    f"Dataset does not exist: {dataset_version_id}"
                ) from exc

    def find_by_fingerprint(self, fingerprint: str) -> DatasetSnapshot | None:
        with self._lock:
            return self._by_fingerprint.get(fingerprint.strip().lower())
