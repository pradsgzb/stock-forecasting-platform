"""Controlled retraining requests and champion-challenger comparison evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import ContinuousTrainingError, DomainValidationError
from stock_predictor.domain.common.identifiers import ModelVersionId, RetrainingRequestId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal
from stock_predictor.domain.mlops.registry import ModelDeploymentScope
from stock_predictor.domain.modeling.evaluation import MetricDirection


class RetrainingTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MINIMUM_NEW_OUTCOMES = "minimum_new_outcomes"
    DATA_DRIFT = "data_drift"
    PREDICTION_DRIFT = "prediction_drift"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    REGIME_CHANGE = "regime_change"
    MANUAL = "manual"


class RetrainingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_STATUS: dict[RetrainingStatus, frozenset[RetrainingStatus]] = {
    RetrainingStatus.PENDING: frozenset(
        {RetrainingStatus.RUNNING, RetrainingStatus.CANCELLED}
    ),
    RetrainingStatus.RUNNING: frozenset(
        {RetrainingStatus.SUCCEEDED, RetrainingStatus.FAILED}
    ),
    RetrainingStatus.SUCCEEDED: frozenset(),
    RetrainingStatus.FAILED: frozenset(),
    RetrainingStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class RetrainingRequest:
    request_id: RetrainingRequestId
    idempotency_key: str
    scope: ModelDeploymentScope
    trigger: RetrainingTrigger
    evidence_references: tuple[str, ...]
    requested_by: str
    requested_at: UtcInstant
    status: RetrainingStatus
    revision: int
    updated_at: UtcInstant
    result_model_version_id: ModelVersionId | None = None
    failure_reason: str | None = None
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        key = self.idempotency_key.strip()
        actor = self.requested_by.strip()
        evidence = tuple(item.strip() for item in self.evidence_references if item.strip())
        failure = self.failure_reason.strip() if self.failure_reason is not None else None
        if not key or not actor or self.revision <= 0:
            raise DomainValidationError("Retraining request identity and revision are required")
        if len(set(evidence)) != len(evidence):
            raise DomainValidationError("Retraining evidence references must be unique")
        if self.updated_at < self.requested_at:
            raise DomainValidationError("Retraining update cannot predate request")
        if self.status is RetrainingStatus.SUCCEEDED and self.result_model_version_id is None:
            raise DomainValidationError("Successful retraining requires a model version")
        if self.status is RetrainingStatus.FAILED and not failure:
            raise DomainValidationError("Failed retraining requires a failure reason")
        if self.status not in {RetrainingStatus.SUCCEEDED, RetrainingStatus.FAILED} and (
            self.result_model_version_id is not None or failure is not None
        ):
            raise DomainValidationError("Only terminal retraining states may carry results")
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(self, "requested_by", actor)
        object.__setattr__(self, "evidence_references", evidence)
        object.__setattr__(self, "failure_reason", failure)
        payload = {
            "request": str(self.request_id),
            "key": key,
            "scope": self.scope.fingerprint,
            "trigger": self.trigger.value,
            "evidence": evidence,
            "requested_by": actor,
            "requested_at": self.requested_at.isoformat(),
            "status": self.status.value,
            "revision": self.revision,
            "updated_at": self.updated_at.isoformat(),
            "result": (
                str(self.result_model_version_id)
                if self.result_model_version_id is not None
                else None
            ),
            "failure": failure,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    def transition(
        self,
        status: RetrainingStatus,
        occurred_at: UtcInstant,
        *,
        result_model_version_id: ModelVersionId | None = None,
        failure_reason: str | None = None,
    ) -> RetrainingRequest:
        if status not in _ALLOWED_STATUS[self.status]:
            raise ContinuousTrainingError(
                f"Illegal retraining transition: {self.status.value} -> {status.value}"
            )
        if occurred_at < self.updated_at:
            raise ContinuousTrainingError("Retraining transition cannot move backward in time")
        return replace(
            self,
            status=status,
            revision=self.revision + 1,
            updated_at=occurred_at,
            result_model_version_id=result_model_version_id,
            failure_reason=failure_reason,
        )


@dataclass(frozen=True, slots=True)
class ChampionChallengerComparison:
    champion_model_version_id: ModelVersionId
    challenger_model_version_id: ModelVersionId
    metric_name: str
    direction: MetricDirection
    champion_value: Decimal
    challenger_value: Decimal
    minimum_improvement: Decimal
    champion_sample_count: int
    challenger_sample_count: int
    minimum_sample_count: int
    compared_at: UtcInstant
    accepted: bool = field(init=False)
    improvement: Decimal = field(init=False)

    def __init__(
        self,
        *,
        champion_model_version_id: ModelVersionId,
        challenger_model_version_id: ModelVersionId,
        metric_name: str,
        direction: MetricDirection,
        champion_value: DecimalInput,
        challenger_value: DecimalInput,
        minimum_improvement: DecimalInput,
        champion_sample_count: int,
        challenger_sample_count: int,
        minimum_sample_count: int,
        compared_at: UtcInstant,
    ) -> None:
        metric = metric_name.strip().lower()
        champion = to_decimal(champion_value, field_name="champion metric")
        challenger = to_decimal(challenger_value, field_name="challenger metric")
        threshold = to_decimal(minimum_improvement, field_name="minimum improvement")
        if not metric or threshold < 0 or minimum_sample_count <= 0:
            raise DomainValidationError("Comparison metric, threshold, and samples are invalid")
        if champion_model_version_id == challenger_model_version_id:
            raise DomainValidationError("Champion and challenger must be different models")
        improvement = (
            champion - challenger
            if direction is MetricDirection.MINIMIZE
            else challenger - champion
        )
        enough_samples = (
            champion_sample_count >= minimum_sample_count
            and challenger_sample_count >= minimum_sample_count
        )
        object.__setattr__(self, "champion_model_version_id", champion_model_version_id)
        object.__setattr__(self, "challenger_model_version_id", challenger_model_version_id)
        object.__setattr__(self, "metric_name", metric)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "champion_value", champion)
        object.__setattr__(self, "challenger_value", challenger)
        object.__setattr__(self, "minimum_improvement", threshold)
        object.__setattr__(self, "champion_sample_count", champion_sample_count)
        object.__setattr__(self, "challenger_sample_count", challenger_sample_count)
        object.__setattr__(self, "minimum_sample_count", minimum_sample_count)
        object.__setattr__(self, "compared_at", compared_at)
        object.__setattr__(self, "improvement", improvement)
        object.__setattr__(self, "accepted", enough_samples and improvement >= threshold)
