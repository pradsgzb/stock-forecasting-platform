"""Data-quality findings, gates, scores, and reconciliation reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import IngestionRunId, ValidationReportId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import to_decimal


class QualityDimension(StrEnum):
    COMPLETENESS = "completeness"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    TIMELINESS = "timeliness"
    CONSISTENCY = "consistency"
    ACCURACY = "accuracy"
    RECONCILIATION = "reconciliation"


class RuleSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RuleOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ValidationStatus(StrEnum):
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class QualityFinding:
    rule_id: str
    dimension: QualityDimension
    severity: RuleSeverity
    outcome: RuleOutcome
    message: str
    record_index: int | None = None
    record_key: str | None = None
    observed: str | None = None
    expected: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.message.strip():
            raise DomainValidationError("Quality finding requires rule ID and message")
        if self.record_index is not None and self.record_index < 0:
            raise DomainValidationError("Quality finding record index cannot be negative")


@dataclass(frozen=True, slots=True, order=True)
class QualityScore:
    """Quality score from 0 through 100, represented exactly."""

    value: Decimal

    def __init__(self, value: Decimal | int | str) -> None:
        normalized = to_decimal(value, field_name="quality score")
        if not Decimal(0) <= normalized <= Decimal(100):
            raise DomainValidationError("Quality score must be between 0 and 100")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    expected_record_count: int | None
    decoded_record_count: int
    page_count: int
    checksums_verified: bool
    findings: tuple[QualityFinding, ...] = ()

    def __post_init__(self) -> None:
        if self.decoded_record_count < 0 or self.page_count <= 0:
            raise DomainValidationError("Reconciliation counts are invalid")

    @property
    def reconciled(self) -> bool:
        count_matches = (
            self.expected_record_count is None
            or self.expected_record_count == self.decoded_record_count
        )
        return count_matches and self.checksums_verified and not any(
            item.outcome is RuleOutcome.FAILED
            and item.severity in {RuleSeverity.ERROR, RuleSeverity.CRITICAL}
            for item in self.findings
        )


@dataclass(frozen=True, slots=True)
class ValidationReport:
    report_id: ValidationReportId
    ingestion_run_id: IngestionRunId
    generated_at: UtcInstant
    status: ValidationStatus
    score: QualityScore
    record_count: int
    findings: tuple[QualityFinding, ...]
    reconciliation: ReconciliationReport
    rule_set_version: str
    report_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        import hashlib

        if self.record_count < 0:
            raise DomainValidationError("Validation record count cannot be negative")
        version = self.rule_set_version.strip()
        if not version:
            raise DomainValidationError("Validation rule-set version cannot be empty")
        object.__setattr__(self, "rule_set_version", version)
        payload = "|".join(
            (
                str(self.report_id),
                str(self.ingestion_run_id),
                self.status.value,
                str(self.score.value),
                str(self.record_count),
                version,
                *(
                    f"{item.rule_id}:{item.outcome.value}:{item.severity.value}:{item.record_index}"
                    for item in self.findings
                ),
            )
        ).encode("utf-8")
        object.__setattr__(self, "report_fingerprint", hashlib.sha256(payload).hexdigest())

    @property
    def accepted(self) -> bool:
        return self.status in {ValidationStatus.PASSED, ValidationStatus.PASSED_WITH_WARNINGS}
