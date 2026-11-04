"""Append-only experiment events for reproducible model development."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, TypeAlias

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import ExperimentRunId
from stock_predictor.domain.common.temporal import UtcInstant

JsonScalar: TypeAlias = str | int | bool | None


class ExperimentEventType(StrEnum):
    STARTED = "started"
    TRIAL_COMPLETED = "trial_completed"
    TRIAL_FAILED = "trial_failed"
    CANDIDATE_SELECTED = "candidate_selected"
    HOLDOUT_EVALUATED = "holdout_evaluated"
    ARTIFACT_CREATED = "artifact_created"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExperimentEvent:
    """Canonical event whose fingerprint makes duplicate delivery idempotent."""

    run_id: ExperimentRunId
    sequence: int
    event_type: ExperimentEventType
    occurred_at: UtcInstant
    details_json: str
    fingerprint: str = field(init=False)

    @classmethod
    def create(
        cls,
        run_id: ExperimentRunId,
        sequence: int,
        event_type: ExperimentEventType,
        occurred_at: UtcInstant,
        details: Mapping[str, JsonScalar],
    ) -> ExperimentEvent:
        canonical = json.dumps(
            dict(details), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return cls(run_id, sequence, event_type, occurred_at, canonical)

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise DomainValidationError("Experiment event sequence must be positive")
        try:
            decoded = json.loads(self.details_json)
        except json.JSONDecodeError as exc:
            raise DomainValidationError("Experiment event details must be JSON") from exc
        if not isinstance(decoded, dict):
            raise DomainValidationError("Experiment event details must be a JSON object")
        canonical = json.dumps(
            decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        object.__setattr__(self, "details_json", canonical)
        payload = "|".join(
            (
                str(self.run_id),
                str(self.sequence),
                self.event_type.value,
                self.occurred_at.isoformat(),
                canonical,
            )
        ).encode("utf-8")
        object.__setattr__(self, "fingerprint", hashlib.sha256(payload).hexdigest())

    @property
    def details(self) -> dict[str, JsonScalar]:
        value = json.loads(self.details_json)
        if not isinstance(value, dict):  # Defensive: constructor already enforces this.
            raise DomainValidationError("Experiment event payload is not an object")
        return value
