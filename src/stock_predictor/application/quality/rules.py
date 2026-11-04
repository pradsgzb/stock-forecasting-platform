"""Deterministic, versioned validation rules for decoded price bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from stock_predictor.application.quality.models import DecodedPriceBar
from stock_predictor.domain.market_data.contracts import PriceBarRequest, RecordOperation
from stock_predictor.domain.market_data.quality import (
    QualityDimension,
    QualityFinding,
    RuleOutcome,
    RuleSeverity,
)
from stock_predictor.ports.calendar_provider import CalendarProvider


@dataclass(frozen=True, slots=True)
class ValidationContext:
    request: PriceBarRequest
    calendars: CalendarProvider
    timeliness_warning_after: timedelta


class MarketDataQualityRule(Protocol):
    rule_id: str
    dimension: QualityDimension
    severity: RuleSeverity

    def evaluate(
        self, records: tuple[DecodedPriceBar, ...], context: ValidationContext
    ) -> tuple[QualityFinding, ...]:
        ...


def _failure(
    rule: MarketDataQualityRule,
    message: str,
    decoded: DecodedPriceBar | None = None,
    *,
    observed: str | None = None,
    expected: str | None = None,
) -> QualityFinding:
    record = None if decoded is None else decoded.record
    return QualityFinding(
        rule_id=rule.rule_id,
        dimension=rule.dimension,
        severity=rule.severity,
        outcome=RuleOutcome.FAILED,
        message=message,
        record_index=None if decoded is None else decoded.record_index,
        record_key=None
        if record is None
        else f"{record.exchange_mic}/{record.symbol}/{record.session_date}/{record.revision}",
        observed=observed,
        expected=expected,
    )


class RequestConformanceRule:
    rule_id = "MDQ-001-request-conformance"
    dimension = QualityDimension.VALIDITY
    severity = RuleSeverity.CRITICAL

    def evaluate(
        self, records: tuple[DecodedPriceBar, ...], context: ValidationContext
    ) -> tuple[QualityFinding, ...]:
        findings: list[QualityFinding] = []
        symbols = set(context.request.symbols)
        for decoded in records:
            item = decoded.record
            if item.provider != context.request.provider:
                findings.append(_failure(self, "Provider does not match request", decoded))
            if item.exchange_mic != context.request.exchange_mic:
                findings.append(_failure(self, "Exchange does not match request", decoded))
            if item.symbol not in symbols:
                findings.append(_failure(self, "Symbol was not requested", decoded))
            if not context.request.start <= item.session_date <= context.request.end:
                findings.append(_failure(self, "Session date is outside request range", decoded))
            if item.frequency is not context.request.frequency:
                findings.append(_failure(self, "Frequency does not match request", decoded))
        return tuple(findings)


class PriceAndVolumeRule:
    rule_id = "MDQ-002-price-volume-validity"
    dimension = QualityDimension.VALIDITY
    severity = RuleSeverity.ERROR

    def evaluate(
        self, records: tuple[DecodedPriceBar, ...], context: ValidationContext
    ) -> tuple[QualityFinding, ...]:
        del context
        findings: list[QualityFinding] = []
        for decoded in records:
            item = decoded.record
            if item.operation is RecordOperation.DELETE:
                continue
            prices = (
                item.open_price,
                item.high_price,
                item.low_price,
                item.close_price,
            )
            if any(value is None or value <= 0 for value in prices):
                findings.append(_failure(self, "OHLC prices must be positive", decoded))
                continue
            if item.volume is None or item.volume < 0:
                findings.append(_failure(self, "Volume cannot be negative", decoded))
            open_price, high_price, low_price, close_price = prices
            if (
                low_price is not None
                and high_price is not None
                and open_price is not None
                and close_price is not None
                and (
                    low_price > high_price
                    or not low_price <= open_price <= high_price
                    or not low_price <= close_price <= high_price
                )
            ):
                findings.append(_failure(self, "OHLC relationship is inconsistent", decoded))
        return tuple(findings)


class DuplicateRecordRule:
    rule_id = "MDQ-003-duplicate-records"
    dimension = QualityDimension.UNIQUENESS
    severity = RuleSeverity.CRITICAL

    def evaluate(
        self, records: tuple[DecodedPriceBar, ...], context: ValidationContext
    ) -> tuple[QualityFinding, ...]:
        del context
        findings: list[QualityFinding] = []
        identifiers: set[str] = set()
        revisions: set[tuple[object, ...]] = set()
        for decoded in records:
            item = decoded.record
            if item.provider_record_id in identifiers:
                findings.append(_failure(self, "Duplicate provider record ID", decoded))
            identifiers.add(item.provider_record_id)
            key = (*item.natural_key, item.revision)
            if key in revisions:
                findings.append(_failure(self, "Duplicate natural key and revision", decoded))
            revisions.add(key)
        return tuple(findings)


class TradingSessionRule:
    rule_id = "MDQ-004-trading-session"
    dimension = QualityDimension.CONSISTENCY
    severity = RuleSeverity.ERROR

    def evaluate(
        self, records: tuple[DecodedPriceBar, ...], context: ValidationContext
    ) -> tuple[QualityFinding, ...]:
        findings: list[QualityFinding] = []
        for decoded in records:
            item = decoded.record
            session = context.calendars.session_or_none(item.exchange_mic, item.session_date)
            if session is None:
                findings.append(_failure(self, "Bar date is not a trading session", decoded))
                continue
            event = item.timeline.event_time
            if not session.opens_at <= event <= session.closes_at:
                findings.append(
                    _failure(
                        self,
                        "Bar event time is outside the regular session",
                        decoded,
                        observed=event.isoformat(),
                        expected=f"{session.opens_at.isoformat()}..{session.closes_at.isoformat()}",
                    )
                )
        return tuple(findings)


class TimelinessRule:
    rule_id = "MDQ-005-processing-timeliness"
    dimension = QualityDimension.TIMELINESS
    severity = RuleSeverity.WARNING

    def evaluate(
        self, records: tuple[DecodedPriceBar, ...], context: ValidationContext
    ) -> tuple[QualityFinding, ...]:
        findings: list[QualityFinding] = []
        for decoded in records:
            item = decoded.record
            latency = item.timeline.processed_at.value - item.timeline.published_at.value
            if latency > context.timeliness_warning_after:
                findings.append(
                    _failure(
                        self,
                        "Provider observation exceeded the timeliness warning threshold",
                        decoded,
                        observed=str(latency),
                        expected=f"<= {context.timeliness_warning_after}",
                    )
                )
        return tuple(findings)


class MonotonicOrderingRule:
    rule_id = "MDQ-006-record-order"
    dimension = QualityDimension.CONSISTENCY
    severity = RuleSeverity.WARNING

    def evaluate(
        self, records: tuple[DecodedPriceBar, ...], context: ValidationContext
    ) -> tuple[QualityFinding, ...]:
        del context
        keys = [
            (
                str(item.record.symbol),
                item.record.session_date,
                item.record.revision,
                item.record.provider_record_id,
            )
            for item in records
        ]
        if keys == sorted(keys):
            return ()
        return (_failure(self, "Decoded records are not in deterministic order"),)


DEFAULT_RULES: tuple[MarketDataQualityRule, ...] = (
    RequestConformanceRule(),
    PriceAndVolumeRule(),
    DuplicateRecordRule(),
    TradingSessionRule(),
    TimelinessRule(),
    MonotonicOrderingRule(),
)
