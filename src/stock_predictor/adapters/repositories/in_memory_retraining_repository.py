"""Thread-safe optimistic retraining request repository."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    ImmutableObjectConflictError,
)
from stock_predictor.domain.common.identifiers import RetrainingRequestId
from stock_predictor.domain.mlops.continuous_training import RetrainingRequest


class InMemoryRetrainingRepository:
    __slots__ = ("_key_index", "_lock", "_requests")

    def __init__(self) -> None:
        self._requests: dict[RetrainingRequestId, RetrainingRequest] = {}
        self._key_index: dict[str, RetrainingRequestId] = {}
        self._lock = RLock()

    def add(self, request: RetrainingRequest) -> None:
        with self._lock:
            existing_id = self._key_index.get(request.idempotency_key)
            if existing_id is not None:
                existing = self._requests[existing_id]
                if existing.fingerprint == request.fingerprint:
                    return
                raise ImmutableObjectConflictError(
                    "Retraining idempotency key is already used"
                )
            if request.request_id in self._requests:
                raise DomainConflictError("Retraining request ID is already present")
            self._requests[request.request_id] = request
            self._key_index[request.idempotency_key] = request.request_id

    def get(self, request_id: RetrainingRequestId) -> RetrainingRequest:
        with self._lock:
            try:
                return self._requests[request_id]
            except KeyError as exc:
                raise DomainNotFoundError(
                    f"Retraining request is not present: {request_id}"
                ) from exc

    def find_by_idempotency_key(self, key: str) -> RetrainingRequest | None:
        normalized = key.strip()
        with self._lock:
            request_id = self._key_index.get(normalized)
            return self._requests.get(request_id) if request_id is not None else None

    def save(self, request: RetrainingRequest, *, expected_revision: int) -> None:
        with self._lock:
            current = self._requests.get(request.request_id)
            if current is None:
                raise DomainNotFoundError(
                    f"Retraining request is not present: {request.request_id}"
                )
            if current.revision != expected_revision:
                raise DomainConflictError("Retraining request revision changed concurrently")
            if request.revision != expected_revision + 1:
                raise DomainConflictError("Retraining request revision must advance exactly once")
            self._requests[request.request_id] = request
