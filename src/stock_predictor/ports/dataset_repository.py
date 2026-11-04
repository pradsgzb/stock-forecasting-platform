"""Port for immutable supervised-learning dataset snapshots."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import DatasetVersionId
from stock_predictor.domain.modeling.datasets import DatasetSnapshot


@runtime_checkable
class DatasetRepository(Protocol):
    def put(self, dataset: DatasetSnapshot) -> None:
        ...

    def get(self, dataset_version_id: DatasetVersionId) -> DatasetSnapshot:
        ...

    def find_by_fingerprint(self, fingerprint: str) -> DatasetSnapshot | None:
        ...
