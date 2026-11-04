"""Tamper-evident audit, outbox, and idempotency records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Mapping, TypeAlias

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import AuditEventId, OutboxEventId
from stock_predictor.domain.common.temporal import UtcInstant

JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_NAME = re.compile(r"^[a-z][a-z0-9_.:-]{1,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._~:+/=-]{8,200}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Mapping[str, JsonValue]) -> str:
    try:
        encoded = json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DomainValidationError("JSON document contains unsupported values") from exc
    if not isinstance(decoded, dict):
        raise DomainValidationError("JSON document must be an object")
    return encoded


@dataclass(frozen=True, slots=True)
class JsonDocument:
    """Canonical, immutable JSON object used at infrastructure boundaries."""

    canonical: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, JsonValue]) -> JsonDocument:
        return cls(_canonical_json(value))

    def __post_init__(self) -> None:
        try:
            decoded = json.loads(self.canonical)
        except json.JSONDecodeError as exc:
            raise DomainValidationError("JSON document is malformed") from exc
        if not isinstance(decoded, dict):
            raise DomainValidationError("JSON document must be an object")
        normalized = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        object.__setattr__(self, "canonical", normalized)

    def as_dict(self) -> dict[str, JsonValue]:
        decoded = json.loads(self.canonical)
        if not isinstance(decoded, dict):  # pragma: no cover - constructor enforces this.
            raise DomainValidationError("JSON document must be an object")
        return decoded

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical.encode()).hexdigest()


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Append-only audit evidence linked through a SHA-256 hash chain."""

    event_id: AuditEventId
    sequence: int
    occurred_at: UtcInstant
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    outcome: AuditOutcome
    correlation_id: str
    request_id: str
    reason: str
    attributes: JsonDocument
    previous_hash: str | None
    event_hash: str = field(init=False)

    def __post_init__(self) -> None:
        actor = self.actor_id.strip()
        action = self.action.strip().lower()
        resource_type = self.resource_type.strip().lower()
        resource_id = self.resource_id.strip()
        correlation = self.correlation_id.strip()
        request = self.request_id.strip()
        reason = self.reason.strip()
        if self.sequence <= 0:
            raise DomainValidationError("Audit sequence must be positive")
        if not actor or not resource_id or not correlation or not request or not reason:
            raise DomainValidationError("Audit identity and reason fields cannot be blank")
        if not _NAME.fullmatch(action) or not _NAME.fullmatch(resource_type):
            raise DomainValidationError("Audit action and resource type are invalid")
        previous = self.previous_hash
        if previous is not None:
            previous = previous.strip().lower()
            if not _SHA256.fullmatch(previous):
                raise DomainValidationError("Previous audit hash must be SHA-256")
        object.__setattr__(self, "actor_id", actor)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "resource_type", resource_type)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "correlation_id", correlation)
        object.__setattr__(self, "request_id", request)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "previous_hash", previous)
        object.__setattr__(self, "event_hash", self._calculate_hash())

    def _calculate_hash(self) -> str:
        payload = {
            "event_id": str(self.event_id),
            "sequence": self.sequence,
            "occurred_at": self.occurred_at.isoformat(),
            "actor_id": self.actor_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "outcome": self.outcome.value,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "reason": self.reason,
            "attributes_sha256": self.attributes.sha256,
            "previous_hash": self.previous_hash,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()

    def verify(self, expected_previous_hash: str | None) -> bool:
        return self.previous_hash == expected_previous_hash and (
            self.event_hash == self._calculate_hash()
        )


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """Transactional event whose immutable business payload is published asynchronously."""

    event_id: OutboxEventId
    aggregate_type: str
    aggregate_id: str
    event_type: str
    event_version: int
    occurred_at: UtcInstant
    available_at: UtcInstant
    payload: JsonDocument
    correlation_id: str
    causation_id: str | None = None
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    published_at: UtcInstant | None = None
    last_error: str | None = None
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        aggregate_type = self.aggregate_type.strip().lower()
        event_type = self.event_type.strip().lower()
        aggregate_id = self.aggregate_id.strip()
        correlation = self.correlation_id.strip()
        causation = self.causation_id.strip() if self.causation_id is not None else None
        if not _NAME.fullmatch(aggregate_type) or not _NAME.fullmatch(event_type):
            raise DomainValidationError("Outbox event names are invalid")
        if not aggregate_id or not correlation or self.event_version <= 0:
            raise DomainValidationError("Outbox identity and version are required")
        if self.available_at < self.occurred_at or self.attempts < 0:
            raise DomainValidationError("Outbox availability and attempts are invalid")
        if self.status is OutboxStatus.PUBLISHED and self.published_at is None:
            raise DomainValidationError("Published outbox event requires published_at")
        if self.status is not OutboxStatus.PUBLISHED and self.published_at is not None:
            raise DomainValidationError("Only published outbox events may have published_at")
        if self.status is OutboxStatus.DEAD_LETTER and not self.last_error:
            raise DomainValidationError("Dead-letter outbox event requires an error")
        object.__setattr__(self, "aggregate_type", aggregate_type)
        object.__setattr__(self, "aggregate_id", aggregate_id)
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "correlation_id", correlation)
        object.__setattr__(self, "causation_id", causation)
        object.__setattr__(self, "fingerprint", self._business_fingerprint())

    def _business_fingerprint(self) -> str:
        payload = {
            "event_id": str(self.event_id),
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload.canonical,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()

    def published(self, at: UtcInstant) -> OutboxEvent:
        if self.status is not OutboxStatus.PENDING or at < self.occurred_at:
            raise DomainValidationError("Only a pending event can be marked published")
        return replace(
            self,
            status=OutboxStatus.PUBLISHED,
            attempts=self.attempts + 1,
            published_at=at,
            last_error=None,
        )

    def failed(self, error: str, *, maximum_attempts: int) -> OutboxEvent:
        detail = error.strip()
        if self.status is not OutboxStatus.PENDING or not detail or maximum_attempts <= 0:
            raise DomainValidationError("Invalid outbox failure transition")
        attempts = self.attempts + 1
        return replace(
            self,
            status=(
                OutboxStatus.DEAD_LETTER
                if attempts >= maximum_attempts
                else OutboxStatus.PENDING
            ),
            attempts=attempts,
            last_error=detail,
        )


class IdempotencyStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Durable exactly-once request identity for externally visible write operations."""

    key: str
    principal_id: str
    operation: str
    request_hash: str
    status: IdempotencyStatus
    created_at: UtcInstant
    expires_at: UtcInstant
    revision: int = 1
    response_status: int | None = None
    response: JsonDocument | None = None

    def __post_init__(self) -> None:
        key = self.key.strip()
        principal = self.principal_id.strip()
        operation = self.operation.strip().lower()
        request_hash = self.request_hash.strip().lower()
        if not _IDEMPOTENCY_KEY.fullmatch(key):
            raise DomainValidationError("Idempotency key has invalid format")
        if not principal or not _NAME.fullmatch(operation):
            raise DomainValidationError("Idempotency principal and operation are required")
        if not _SHA256.fullmatch(request_hash):
            raise DomainValidationError("Idempotency request hash must be SHA-256")
        if self.expires_at <= self.created_at or self.revision <= 0:
            raise DomainValidationError("Idempotency expiry and revision are invalid")
        completed = self.status is IdempotencyStatus.COMPLETED
        if completed != (self.response_status is not None and self.response is not None):
            raise DomainValidationError("Completed idempotency record requires a response")
        if self.response_status is not None and not 100 <= self.response_status <= 599:
            raise DomainValidationError("Idempotency response status is invalid")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "principal_id", principal)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "request_hash", request_hash)

    def complete(
        self,
        *,
        response_status: int,
        response: JsonDocument,
    ) -> IdempotencyRecord:
        if self.status is not IdempotencyStatus.PROCESSING:
            raise DomainValidationError("Only processing requests can be completed")
        return replace(
            self,
            status=IdempotencyStatus.COMPLETED,
            revision=self.revision + 1,
            response_status=response_status,
            response=response,
        )

    def fail(self) -> IdempotencyRecord:
        if self.status is not IdempotencyStatus.PROCESSING:
            raise DomainValidationError("Only processing requests can fail")
        return replace(
            self,
            status=IdempotencyStatus.FAILED,
            revision=self.revision + 1,
        )
