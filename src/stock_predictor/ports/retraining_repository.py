"""Port for controlled retraining request state."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import RetrainingRequestId
from stock_predictor.domain.mlops.continuous_training import RetrainingRequest


@runtime_checkable
class RetrainingRepository(Protocol):
    def add(self, request: RetrainingRequest) -> None:
        ...

    def get(self, request_id: RetrainingRequestId) -> RetrainingRequest:
        ...

    def find_by_idempotency_key(self, key: str) -> RetrainingRequest | None:
        ...

    def save(self, request: RetrainingRequest, *, expected_revision: int) -> None:
        ...
