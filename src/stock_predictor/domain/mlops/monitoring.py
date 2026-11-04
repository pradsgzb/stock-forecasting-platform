"""Drift, performance, and alert evidence for production model monitoring."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum, StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    DriftReportId,
    ModelVersionId,
    MonitoringAlertId,
    MonitoringSnapshotId,
)
from stock_predictor.domain.common.temporal import InstantInterval, UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal
from stock_predictor.domain.mlops.feedback import FeedbackSummary

_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MonitoringSeverity(IntEnum):
    INFORMATIONAL = 0
    WARNING = 1
    CRITICAL = 2


class DriftKind(StrEnum):
    FEATURE = "feature"
    PREDICTION = "prediction"
    DATA_QUALITY = "data_quality"
    PERFORMANCE = "performance"


@dataclass(frozen=True, slots=True)
class DriftMeasure:
    name: str
    value: Decimal
    warning_threshold: Decimal
    critical_threshold: Decimal
    severity: MonitoringSeverity = field(init=False)

    def __init__(
        self,
        name: str,
        value: DecimalInput,
        warning_threshold: DecimalInput,
        critical_threshold: DecimalInput,
    ) -> None:
        normalized = name.strip().lower()
        measured = to_decimal(value, field_name=f"drift measure {normalized}")
        warning = to_decimal(warning_threshold, field_name="warning threshold")
        critical = to_decimal(critical_threshold, field_name="critical threshold")
        if not _NAME.fullmatch(normalized):
            raise DomainValidationError("Drift measure name is invalid")
        if warning < 0 or critical <= warning or measured < 0:
            raise DomainValidationError("Drift thresholds and values must be ordered")
        severity = MonitoringSeverity.INFORMATIONAL
        if measured >= critical:
            severity = MonitoringSeverity.CRITICAL
        elif measured >= warning:
            severity = MonitoringSeverity.WARNING
        object.__setattr__(self, "name", normalized)
        object.__setattr__(self, "value", measured)
        object.__setattr__(self, "warning_threshold", warning)
        object.__setattr__(self, "critical_threshold", critical)
        object.__setattr__(self, "severity", severity)


@dataclass(frozen=True, slots=True)
class DriftReport:
    report_id: DriftReportId
    model_version_id: ModelVersionId
    kind: DriftKind
    subject_key: str
    reference_window: InstantInterval
    current_window: InstantInterval
    reference_sample_count: int
    current_sample_count: int
    measures: tuple[DriftMeasure, ...]
    created_at: UtcInstant
    severity: MonitoringSeverity = field(init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        subject = self.subject_key.strip().lower()
        names = tuple(item.name for item in self.measures)
        if not subject or self.reference_sample_count <= 0 or self.current_sample_count <= 0:
            raise DomainValidationError("Drift report requires subject and non-empty samples")
        if self.current_window.start < self.reference_window.end:
            raise DomainValidationError("Drift current window must follow the reference window")
        if not self.measures or len(set(names)) != len(names):
            raise DomainValidationError("Drift report requires unique measures")
        if self.created_at < self.current_window.end:
            raise DomainValidationError("Drift report cannot predate its current window")
        severity = max(item.severity for item in self.measures)
        object.__setattr__(self, "subject_key", subject)
        object.__setattr__(self, "severity", severity)
        payload = {
            "report": str(self.report_id),
            "model": str(self.model_version_id),
            "kind": self.kind.value,
            "subject": subject,
            "reference": (
                self.reference_window.start.isoformat(),
                self.reference_window.end.isoformat(),
                self.reference_sample_count,
            ),
            "current": (
                self.current_window.start.isoformat(),
                self.current_window.end.isoformat(),
                self.current_sample_count,
            ),
            "measures": [
                (
                    item.name,
                    str(item.value),
                    str(item.warning_threshold),
                    str(item.critical_threshold),
                    int(item.severity),
                )
                for item in self.measures
            ],
            "created_at": self.created_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())


@dataclass(frozen=True, slots=True)
class PerformanceSnapshot:
    snapshot_id: MonitoringSnapshotId
    summary: FeedbackSummary
    baseline_summary_fingerprint: str | None
    metric_degradation: tuple[tuple[str, Decimal], ...]
    severity: MonitoringSeverity
    created_at: UtcInstant
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.metric_degradation)
        if len(set(names)) != len(names):
            raise DomainValidationError("Performance degradation metrics must be unique")
        if self.created_at < self.summary.generated_at:
            raise DomainValidationError("Performance snapshot cannot predate its summary")
        baseline = (
            self.baseline_summary_fingerprint.strip().lower()
            if self.baseline_summary_fingerprint is not None
            else None
        )
        if baseline is not None and not _SHA256.fullmatch(baseline):
            raise DomainValidationError("Baseline feedback fingerprint must be SHA-256")
        object.__setattr__(self, "baseline_summary_fingerprint", baseline)
        payload = {
            "snapshot": str(self.snapshot_id),
            "summary": self.summary.fingerprint,
            "baseline": baseline,
            "degradation": [(name, str(value)) for name, value in self.metric_degradation],
            "severity": int(self.severity),
            "created_at": self.created_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())


@dataclass(frozen=True, slots=True)
class MonitoringAlert:
    alert_id: MonitoringAlertId
    model_version_id: ModelVersionId
    severity: MonitoringSeverity
    category: str
    title: str
    detail: str
    evidence_reference: str
    raised_at: UtcInstant

    def __post_init__(self) -> None:
        category = self.category.strip().lower()
        title = self.title.strip()
        detail = self.detail.strip()
        evidence = self.evidence_reference.strip()
        if not _NAME.fullmatch(category) or not title or not detail or not evidence:
            raise DomainValidationError("Monitoring alert fields cannot be blank")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "detail", detail)
        object.__setattr__(self, "evidence_reference", evidence)
