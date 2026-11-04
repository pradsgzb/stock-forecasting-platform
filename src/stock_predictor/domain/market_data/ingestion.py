"""Immutable raw-object and ingestion-manifest domain models."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import IngestionRunId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.identifiers import ProviderName
from stock_predictor.domain.market_data.contracts import PriceBarRequest

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True, order=True)
class Sha256Digest:
    """Validated lowercase SHA-256 hexadecimal digest."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not _SHA256_PATTERN.fullmatch(normalized):
            msg = f"Invalid SHA-256 digest: {self.value!r}"
            raise DomainValidationError(msg)
        object.__setattr__(self, "value", normalized)

    @classmethod
    def from_bytes(cls, payload: bytes) -> Sha256Digest:
        return cls(hashlib.sha256(payload).hexdigest())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RawObjectDescriptor:
    """Reference to immutable content-addressed bytes."""

    digest: Sha256Digest
    storage_key: str
    byte_count: int

    def __post_init__(self) -> None:
        key = self.storage_key.strip()
        path = PurePosixPath(key)
        if (
            not key
            or "\\" in key
            or path.is_absolute()
            or key != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise DomainValidationError("Raw object storage key must be a safe relative path")
        if self.byte_count <= 0:
            raise DomainValidationError("Raw object byte count must be positive")
        object.__setattr__(self, "storage_key", key)


@dataclass(frozen=True, slots=True)
class IngestionPageManifest:
    """Immutable lineage for one fetched and durably stored provider page."""

    page_number: int
    cursor_in: str | None
    cursor_out: str | None
    provider_request_id: str
    schema_version: str
    content_type: str
    advertised_record_count: int | None
    raw_object: RawObjectDescriptor
    retrieved_at: UtcInstant

    def __post_init__(self) -> None:
        if self.page_number <= 0:
            raise DomainValidationError("Ingestion page number must be positive")
        request_id = self.provider_request_id.strip()
        schema_version = self.schema_version.strip()
        content_type = self.content_type.strip().lower()
        if not request_id or len(request_id) > 512:
            raise DomainValidationError(
                "Provider request ID must contain 1 to 512 characters"
            )
        if not schema_version or len(schema_version) > 128:
            raise DomainValidationError(
                "Provider schema version must contain 1 to 128 characters"
            )
        if not content_type or len(content_type) > 256:
            raise DomainValidationError(
                "Provider content type must contain 1 to 256 characters"
            )
        if self.advertised_record_count is not None and self.advertised_record_count < 0:
            raise DomainValidationError("Advertised record count cannot be negative")
        for name, cursor in (("cursor_in", self.cursor_in), ("cursor_out", self.cursor_out)):
            if cursor is not None and (not cursor or len(cursor) > 4_096):
                raise DomainValidationError(
                    f"{name} must be non-empty and no longer than 4096 characters"
                )
        object.__setattr__(self, "provider_request_id", request_id)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "content_type", content_type)


class IngestionStatus(StrEnum):
    """Terminal state of an immutable ingestion manifest."""

    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestionManifest:
    """Immutable terminal record for one logical ingestion request."""

    run_id: IngestionRunId
    idempotency_key: str
    provider: ProviderName
    request: PriceBarRequest
    started_at: UtcInstant
    completed_at: UtcInstant
    status: IngestionStatus
    pages: tuple[IngestionPageManifest, ...]
    failure_reason: str | None = None
    manifest_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        key = self.idempotency_key.strip()
        if not key or len(key) > 256:
            raise DomainValidationError(
                "Ingestion idempotency key must contain 1 to 256 characters"
            )
        if self.completed_at < self.started_at:
            raise DomainValidationError("Ingestion completion cannot precede start")
        if self.provider != self.request.provider:
            raise DomainValidationError("Manifest provider must match request provider")
        expected_pages = tuple(range(1, len(self.pages) + 1))
        if tuple(page.page_number for page in self.pages) != expected_pages:
            raise DomainValidationError("Ingestion pages must be contiguous and ordered")
        if self.status is IngestionStatus.COMPLETED and not self.pages:
            raise DomainValidationError("Completed ingestion requires at least one page")
        if self.status is IngestionStatus.COMPLETED and self.failure_reason is not None:
            raise DomainValidationError("Completed ingestion cannot have a failure reason")
        normalized_failure = (
            None if self.failure_reason is None else self.failure_reason.strip()
        )
        if self.status is IngestionStatus.FAILED and not normalized_failure:
            raise DomainValidationError("Failed ingestion requires a failure reason")
        if normalized_failure is not None and len(normalized_failure) > 4_096:
            raise DomainValidationError("Ingestion failure reason is too long")
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(self, "failure_reason", normalized_failure)
        payload = {
            "run_id": str(self.run_id),
            "idempotency_key": key,
            "provider": str(self.provider),
            "request_fingerprint": self.request.request_fingerprint,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "status": self.status.value,
            "failure_reason": normalized_failure,
            "pages": [
                {
                    "page_number": page.page_number,
                    "cursor_in": page.cursor_in,
                    "cursor_out": page.cursor_out,
                    "provider_request_id": page.provider_request_id,
                    "schema_version": page.schema_version,
                    "content_type": page.content_type,
                    "advertised_record_count": page.advertised_record_count,
                    "raw_digest": str(page.raw_object.digest),
                    "raw_storage_key": page.raw_object.storage_key,
                    "raw_byte_count": page.raw_object.byte_count,
                    "retrieved_at": page.retrieved_at.isoformat(),
                }
                for page in self.pages
            ],
        }
        object.__setattr__(
            self,
            "manifest_fingerprint",
            hashlib.sha256(_canonical_json(payload)).hexdigest(),
        )

    @property
    def advertised_record_count(self) -> int | None:
        counts = tuple(page.advertised_record_count for page in self.pages)
        if any(count is None for count in counts):
            return None
        return sum(count for count in counts if count is not None)


@dataclass(frozen=True, slots=True)
class IngestionCheckpoint:
    """Mutable operational cursor represented as an immutable value."""

    run_id: IngestionRunId
    idempotency_key: str
    request_fingerprint: str
    next_page_number: int
    next_cursor: str | None
    completed_pages: tuple[IngestionPageManifest, ...]
    started_at: UtcInstant
    updated_at: UtcInstant

    def __post_init__(self) -> None:
        key = self.idempotency_key.strip()
        fingerprint = self.request_fingerprint.strip().lower()
        if not key or len(key) > 256:
            raise DomainValidationError(
                "Checkpoint idempotency key must contain 1 to 256 characters"
            )
        if not _SHA256_PATTERN.fullmatch(fingerprint):
            raise DomainValidationError("Checkpoint request fingerprint must be SHA-256")
        expected_pages = tuple(range(1, len(self.completed_pages) + 1))
        if tuple(page.page_number for page in self.completed_pages) != expected_pages:
            raise DomainValidationError("Checkpoint pages must be contiguous and ordered")
        if self.next_page_number != len(self.completed_pages) + 1:
            raise DomainValidationError("Checkpoint page number must follow completed pages")
        expected_cursor = (
            None if not self.completed_pages else self.completed_pages[-1].cursor_out
        )
        if self.next_cursor != expected_cursor:
            raise DomainValidationError(
                "Checkpoint next cursor must match the final completed page"
            )
        if self.updated_at < self.started_at:
            raise DomainValidationError("Checkpoint update cannot precede start")
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(self, "request_fingerprint", fingerprint)
