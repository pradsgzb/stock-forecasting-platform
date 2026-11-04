"""Market-data decode, reconciliation, validation, scoring, and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.application.quality.models import DecodedPriceBar, ValidatedPriceBarBatch
from stock_predictor.application.quality.rules import (
    DEFAULT_RULES,
    MarketDataQualityRule,
    ValidationContext,
)
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import (
    DomainValidationError,
    ProviderContractError,
)
from stock_predictor.domain.common.identifiers import ValidationReportId
from stock_predictor.domain.market_data.contracts import MarketDataPage
from stock_predictor.domain.market_data.ingestion import IngestionManifest
from stock_predictor.domain.market_data.quality import (
    QualityDimension,
    QualityFinding,
    QualityScore,
    ReconciliationReport,
    RuleOutcome,
    RuleSeverity,
    ValidationReport,
    ValidationStatus,
)
from stock_predictor.ports.calendar_provider import CalendarProvider
from stock_predictor.ports.raw_object_store import RawObjectStore
from stock_predictor.ports.validation_report_repository import ValidationReportRepository


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    rule_set_version: str = "price-bars-v1"
    minimum_acceptable_score: Decimal = Decimal("80")
    timeliness_warning_after: timedelta = timedelta(hours=6)
    critical_penalty: Decimal = Decimal("30")
    error_penalty: Decimal = Decimal("10")
    warning_penalty: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if not self.rule_set_version.strip():
            raise DomainValidationError("Validation rule-set version cannot be empty")
        if not Decimal(0) <= self.minimum_acceptable_score <= Decimal(100):
            raise DomainValidationError("Minimum quality score must be between 0 and 100")
        if self.timeliness_warning_after < timedelta():
            raise DomainValidationError("Timeliness threshold cannot be negative")
        if any(
            value < 0
            for value in (self.critical_penalty, self.error_penalty, self.warning_penalty)
        ):
            raise DomainValidationError("Quality penalties cannot be negative")


class MarketDataQualityService:
    __slots__ = (
        "_calendars",
        "_clock",
        "_policy",
        "_providers",
        "_raw_objects",
        "_reports",
        "_rules",
    )

    def __init__(
        self,
        providers: MarketDataProviderRegistry,
        raw_objects: RawObjectStore,
        calendars: CalendarProvider,
        reports: ValidationReportRepository,
        clock: Clock,
        *,
        rules: tuple[MarketDataQualityRule, ...] = DEFAULT_RULES,
        policy: ValidationPolicy | None = None,
    ) -> None:
        if len({item.rule_id for item in rules}) != len(rules):
            raise DomainValidationError("Validation rule IDs must be unique")
        self._providers = providers
        self._raw_objects = raw_objects
        self._calendars = calendars
        self._reports = reports
        self._clock = clock
        self._rules = rules
        self._policy = policy or ValidationPolicy()

    def validate(self, manifest: IngestionManifest) -> ValidatedPriceBarBatch:
        provider = self._providers.get(manifest.provider)
        decoded: list[DecodedPriceBar] = []
        reconciliation_findings: list[QualityFinding] = []
        for page_manifest in manifest.pages:
            payload = self._raw_objects.read(page_manifest.raw_object)
            page = MarketDataPage(
                provider=manifest.provider,
                request_fingerprint=manifest.request.request_fingerprint,
                provider_request_id=page_manifest.provider_request_id,
                retrieved_at=page_manifest.retrieved_at,
                schema_version=page_manifest.schema_version,
                content_type=page_manifest.content_type,
                raw_payload=payload,
                next_cursor=page_manifest.cursor_out,
                advertised_record_count=page_manifest.advertised_record_count,
            )
            try:
                page_records = provider.decode_price_bars(page)
            except ProviderContractError as exc:
                reconciliation_findings.append(
                    QualityFinding(
                        rule_id="MDQ-000-payload-decode",
                        dimension=QualityDimension.VALIDITY,
                        severity=RuleSeverity.CRITICAL,
                        outcome=RuleOutcome.FAILED,
                        message="Provider payload could not be decoded under its schema contract",
                        observed=type(exc).__name__,
                        expected=page_manifest.schema_version,
                    )
                )
                continue
            if (
                page_manifest.advertised_record_count is not None
                and page_manifest.advertised_record_count != len(page_records)
            ):
                reconciliation_findings.append(
                    QualityFinding(
                        rule_id="MDQ-000-page-record-count",
                        dimension=QualityDimension.RECONCILIATION,
                        severity=RuleSeverity.ERROR,
                        outcome=RuleOutcome.FAILED,
                        message="Decoded page count does not match provider-advertised count",
                        observed=str(len(page_records)),
                        expected=str(page_manifest.advertised_record_count),
                    )
                )
            decoded.extend(
                DecodedPriceBar(
                    record=record,
                    page_number=page_manifest.page_number,
                    record_index=index,
                    source_digest=page_manifest.raw_object.digest,
                )
                for index, record in enumerate(page_records)
            )
        expected = manifest.advertised_record_count
        if expected is not None and expected != len(decoded):
            reconciliation_findings.append(
                QualityFinding(
                    rule_id="MDQ-000-manifest-record-count",
                    dimension=QualityDimension.RECONCILIATION,
                    severity=RuleSeverity.ERROR,
                    outcome=RuleOutcome.FAILED,
                    message="Decoded manifest count does not match advertised count",
                    observed=str(len(decoded)),
                    expected=str(expected),
                )
            )
        reconciliation = ReconciliationReport(
            expected_record_count=expected,
            decoded_record_count=len(decoded),
            page_count=len(manifest.pages),
            checksums_verified=True,
            findings=tuple(reconciliation_findings),
        )
        context = ValidationContext(
            request=manifest.request,
            calendars=self._calendars,
            timeliness_warning_after=self._policy.timeliness_warning_after,
        )
        findings = list(reconciliation_findings)
        records = tuple(decoded)
        for rule in self._rules:
            failures = rule.evaluate(records, context)
            findings.extend(failures)
            if not failures:
                findings.append(
                    QualityFinding(
                        rule_id=rule.rule_id,
                        dimension=rule.dimension,
                        severity=rule.severity,
                        outcome=RuleOutcome.PASSED,
                        message="Rule passed",
                    )
                )
        score = self._score(tuple(findings))
        status = self._status(tuple(findings), score)
        report = ValidationReport(
            report_id=ValidationReportId.new(),
            ingestion_run_id=manifest.run_id,
            generated_at=self._clock.now(),
            status=status,
            score=score,
            record_count=len(records),
            findings=tuple(findings),
            reconciliation=reconciliation,
            rule_set_version=self._policy.rule_set_version,
        )
        self._reports.add(report)
        return ValidatedPriceBarBatch(manifest, records, report)

    def _score(self, findings: tuple[QualityFinding, ...]) -> QualityScore:
        penalties = {
            RuleSeverity.CRITICAL: self._policy.critical_penalty,
            RuleSeverity.ERROR: self._policy.error_penalty,
            RuleSeverity.WARNING: self._policy.warning_penalty,
            RuleSeverity.INFO: Decimal(0),
        }
        deduction = sum(
            (penalties[item.severity] for item in findings if item.outcome is RuleOutcome.FAILED),
            start=Decimal(0),
        )
        return QualityScore(max(Decimal(0), Decimal(100) - deduction))

    def _status(
        self, findings: tuple[QualityFinding, ...], score: QualityScore
    ) -> ValidationStatus:
        failed = tuple(item for item in findings if item.outcome is RuleOutcome.FAILED)
        if any(item.severity is RuleSeverity.CRITICAL for item in failed):
            return ValidationStatus.REJECTED
        if any(item.severity is RuleSeverity.ERROR for item in failed):
            return ValidationStatus.QUARANTINED
        if score.value < self._policy.minimum_acceptable_score:
            return ValidationStatus.QUARANTINED
        if any(item.severity is RuleSeverity.WARNING for item in failed):
            return ValidationStatus.PASSED_WITH_WARNINGS
        return ValidationStatus.PASSED
