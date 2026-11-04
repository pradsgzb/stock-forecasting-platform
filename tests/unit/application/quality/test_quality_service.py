from dataclasses import replace
from datetime import date
from pathlib import Path

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.adapters.market_data.synthetic_provider import SyntheticMarketDataProvider
from stock_predictor.adapters.repositories.in_memory_ingestion_catalog import (
    InMemoryIngestionCatalog,
)
from stock_predictor.adapters.repositories.in_memory_validation_repository import (
    InMemoryValidationReportRepository,
)
from stock_predictor.adapters.storage.local_raw_object_store import (
    LocalContentAddressedRawObjectStore,
)
from stock_predictor.application.market_data.ingestion import MarketDataIngestionService
from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.application.quality.service import (
    MarketDataQualityService,
    ValidationPolicy,
)
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import DataQualityGateError, DomainValidationError
from stock_predictor.domain.market_data.contracts import PriceBarRequest
from stock_predictor.domain.market_data.quality import ValidationStatus


def _validate(
    tmp_path: Path,
    records,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    *,
    policy: ValidationPolicy | None = None,
    advertised_count: int | None = None,
):
    clock = FixedClock(fixed_instant)
    provider = SyntheticMarketDataProvider(tuple(records), clock)
    providers = MarketDataProviderRegistry((provider,))
    raw_store = LocalContentAddressedRawObjectStore(tmp_path)
    manifest = MarketDataIngestionService(
        providers, raw_store, InMemoryIngestionCatalog(), clock
    ).ingest_price_bars(
        PriceBarRequest(
            synthetic_provider_name,
            xnys,
            (sample_symbol,),
            date(2025, 7, 1),
            date(2025, 7, 3),
            page_size=100,
        )
    )
    if advertised_count is not None:
        page = replace(manifest.pages[0], advertised_record_count=advertised_count)
        manifest = replace(manifest, pages=(page,))
    reports = InMemoryValidationReportRepository()
    service = MarketDataQualityService(
        providers,
        raw_store,
        ExchangeCalendarsProvider(exchange_catalog),
        reports,
        clock,
        policy=policy,
    )
    batch = service.validate(manifest)
    return batch, reports


def test_quality_service_accepts_valid_records_and_persists_report(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    batch, reports = _validate(
        tmp_path,
        (make_provider_bar(date(2025, 7, 2)),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )

    assert batch.report.status is ValidationStatus.PASSED
    assert batch.report.score.value == 100
    assert batch.report.reconciliation.reconciled
    assert reports.latest_for_run(batch.manifest.run_id) == batch.report
    batch.require_accepted()


def test_quality_service_classifies_warning_error_and_critical_failures(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    warning, _ = _validate(
        tmp_path / "warning",
        (make_provider_bar(processed_delay_minutes=400),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    assert warning.report.status is ValidationStatus.PASSED_WITH_WARNINGS
    assert warning.report.score.value == 98

    error, _ = _validate(
        tmp_path / "error",
        (make_provider_bar(volume="-1"),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    assert error.report.status is ValidationStatus.QUARANTINED
    try:
        error.require_accepted()
    except DataQualityGateError as exc:
        assert "quarantined" in str(exc)
    else:
        raise AssertionError("quarantined batch must fail the gate")

    duplicate = make_provider_bar(provider_record_id="same")
    critical, _ = _validate(
        tmp_path / "critical",
        (duplicate, duplicate),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    assert critical.report.status is ValidationStatus.REJECTED


def test_quality_service_reconciliation_count_mismatch_is_quarantined(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    batch, _ = _validate(
        tmp_path,
        (make_provider_bar(),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
        advertised_count=2,
    )

    assert batch.report.status is ValidationStatus.QUARANTINED
    assert not batch.report.reconciliation.reconciled
    messages = {item.message for item in batch.report.findings}
    assert "Decoded page count does not match provider-advertised count" in messages
    assert "Decoded manifest count does not match advertised count" in messages


def test_quality_policy_validation_and_score_threshold(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    policy = ValidationPolicy(minimum_acceptable_score=99)
    batch, _ = _validate(
        tmp_path,
        (make_provider_bar(processed_delay_minutes=400),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
        policy=policy,
    )
    assert batch.report.status is ValidationStatus.QUARANTINED

    for invalid in (
        {"rule_set_version": ""},
        {"minimum_acceptable_score": -1},
        {"timeliness_warning_after": __import__("datetime").timedelta(seconds=-1)},
        {"warning_penalty": -1},
    ):
        try:
            ValidationPolicy(**invalid)
        except DomainValidationError:
            pass
        else:
            raise AssertionError(f"policy should reject {invalid}")


def test_quality_service_rejects_duplicate_rule_ids(
    tmp_path,
    fixed_instant,
    exchange_catalog,
) -> None:
    from stock_predictor.application.quality.rules import RequestConformanceRule

    provider = SyntheticMarketDataProvider((), FixedClock(fixed_instant))
    providers = MarketDataProviderRegistry((provider,))
    try:
        MarketDataQualityService(
            providers,
            LocalContentAddressedRawObjectStore(tmp_path),
            ExchangeCalendarsProvider(exchange_catalog),
            InMemoryValidationReportRepository(),
            FixedClock(fixed_instant),
            rules=(RequestConformanceRule(), RequestConformanceRule()),
        )
    except DomainValidationError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate rules must be rejected")


def test_quality_service_records_schema_decode_failure_as_rejected(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    from stock_predictor.domain.common.errors import ProviderContractError

    clock = FixedClock(fixed_instant)
    delegate = SyntheticMarketDataProvider((make_provider_bar(),), clock)
    raw = LocalContentAddressedRawObjectStore(tmp_path)
    manifest = MarketDataIngestionService(
        MarketDataProviderRegistry((delegate,)),
        raw,
        InMemoryIngestionCatalog(),
        clock,
    ).ingest_price_bars(
        PriceBarRequest(
            synthetic_provider_name,
            xnys,
            (sample_symbol,),
            date(2025, 7, 1),
            date(2025, 7, 3),
        )
    )

    class FailingDecoder:
        @property
        def capabilities(self):
            return delegate.capabilities

        def fetch_price_bars(self, request, *, cursor=None):
            return delegate.fetch_price_bars(request, cursor=cursor)

        def decode_price_bars(self, page):
            raise ProviderContractError("unsupported schema")

    service = MarketDataQualityService(
        MarketDataProviderRegistry((FailingDecoder(),)),
        raw,
        ExchangeCalendarsProvider(exchange_catalog),
        InMemoryValidationReportRepository(),
        clock,
    )
    batch = service.validate(manifest)

    assert batch.report.status is ValidationStatus.REJECTED
    assert batch.report.record_count == 0
    assert any(
        item.rule_id == "MDQ-000-payload-decode" for item in batch.report.findings
    )
