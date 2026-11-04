from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.adapters.market_data.synthetic_provider import SyntheticMarketDataProvider
from stock_predictor.adapters.repositories.in_memory_ingestion_catalog import (
    InMemoryIngestionCatalog,
)
from stock_predictor.adapters.repositories.in_memory_price_bar_repository import (
    InMemoryPriceBarRepository,
)
from stock_predictor.adapters.repositories.in_memory_validation_repository import (
    InMemoryValidationReportRepository,
)
from stock_predictor.adapters.storage.local_raw_object_store import (
    LocalContentAddressedRawObjectStore,
)
from stock_predictor.application.market_data.ingestion import MarketDataIngestionService
from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.application.normalization.service import PriceBarNormalizationService
from stock_predictor.application.quality.service import MarketDataQualityService
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import (
    DataQualityGateError,
    DomainConflictError,
)
from stock_predictor.domain.common.money import Currency
from stock_predictor.domain.market_data.contracts import PriceBarRequest, RecordOperation


def _accepted_batch(
    tmp_path: Path,
    records,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
):
    clock = FixedClock(fixed_instant)
    provider = SyntheticMarketDataProvider(tuple(records), clock)
    registry = MarketDataProviderRegistry((provider,))
    raw = LocalContentAddressedRawObjectStore(tmp_path)
    manifest = MarketDataIngestionService(
        registry, raw, InMemoryIngestionCatalog(), clock
    ).ingest_price_bars(
        PriceBarRequest(
            synthetic_provider_name,
            xnys,
            (sample_symbol,),
            date(2025, 7, 1),
            date(2025, 7, 3),
        )
    )
    return MarketDataQualityService(
        registry,
        raw,
        ExchangeCalendarsProvider(exchange_catalog),
        InMemoryValidationReportRepository(),
        clock,
    ).validate(manifest)


def test_normalization_is_idempotent_and_preserves_lineage(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    mapped_instrument_repository,
) -> None:
    instruments, instrument = mapped_instrument_repository
    batch = _accepted_batch(
        tmp_path,
        (make_provider_bar(),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    repository = InMemoryPriceBarRepository()
    service = PriceBarNormalizationService(instruments, repository)

    first = service.normalize(batch)
    second = service.normalize(batch)

    assert first == second
    assert first.validation_report_fingerprint == batch.report.report_fingerprint
    bar = first.bars[0]
    assert bar.key.instrument_id == instrument.instrument_id
    assert bar.values is not None
    assert str(bar.values.close_price.amount) == "103"
    assert bar.source_digest == batch.records[0].source_digest
    assert repository.latest_revision(bar.key) == bar


def test_normalization_appends_correction_and_tombstone(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    mapped_instrument_repository,
) -> None:
    instruments, _ = mapped_instrument_repository
    records = (
        make_provider_bar(revision=0, close_price="103", provider_record_id="r0"),
        make_provider_bar(revision=1, close_price="104", provider_record_id="r1"),
        make_provider_bar(
            revision=2,
            operation=RecordOperation.DELETE,
            provider_record_id="r2",
        ),
    )
    batch = _accepted_batch(
        tmp_path,
        records,
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    repository = InMemoryPriceBarRepository()
    result = PriceBarNormalizationService(instruments, repository).normalize(batch)

    assert len(result.bars) == 3
    first, second, third = result.bars
    assert second.supersedes_bar_id == first.bar_id
    assert third.supersedes_bar_id == second.bar_id
    assert third.is_tombstone
    assert repository.as_known_at(first.key, fixed_instant) is None


def test_normalization_rejects_unknown_symbol_and_currency_mismatch(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    mapped_instrument_repository,
) -> None:
    instruments, _ = mapped_instrument_repository
    batch = _accepted_batch(
        tmp_path / "unknown",
        (make_provider_bar(),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
        InMemoryInstrumentRepository,
    )

    with pytest.raises(DataQualityGateError, match="point-in-time instrument mapping"):
        PriceBarNormalizationService(
            InMemoryInstrumentRepository(), InMemoryPriceBarRepository()
        ).normalize(batch)

    record = replace(batch.records[0].record, currency=Currency("EUR"))
    changed = replace(batch, records=(replace(batch.records[0], record=record),))
    with pytest.raises(DataQualityGateError, match="does not match instrument currency"):
        PriceBarNormalizationService(instruments, InMemoryPriceBarRepository()).normalize(
            changed
        )


def test_normalization_requires_accepted_batch(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    mapped_instrument_repository,
) -> None:
    instruments, _ = mapped_instrument_repository
    batch = _accepted_batch(
        tmp_path,
        (make_provider_bar(volume="-1"),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    with pytest.raises(DataQualityGateError, match="quality gate"):
        PriceBarNormalizationService(instruments, InMemoryPriceBarRepository()).normalize(
            batch
        )


def test_normalization_rejects_older_revision_after_newer_revision(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    mapped_instrument_repository,
) -> None:
    instruments, _ = mapped_instrument_repository
    repository = InMemoryPriceBarRepository()
    service = PriceBarNormalizationService(instruments, repository)
    newer = _accepted_batch(
        tmp_path / "newer",
        (make_provider_bar(revision=2, provider_record_id="newer"),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    service.normalize(newer)
    older = _accepted_batch(
        tmp_path / "older",
        (make_provider_bar(revision=1, provider_record_id="older"),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    with pytest.raises(DomainConflictError, match="revision conflicts"):
        service.normalize(older)


def test_normalization_identity_is_independent_of_provider_pagination(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    mapped_instrument_repository,
) -> None:
    from stock_predictor.domain.market_data.ingestion import Sha256Digest

    instruments, _ = mapped_instrument_repository
    batch = _accepted_batch(
        tmp_path,
        (make_provider_bar(provider_record_id="stable-provider-record"),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    repository = InMemoryPriceBarRepository()
    service = PriceBarNormalizationService(instruments, repository)
    first = service.normalize(batch).bars[0]
    relocated = replace(
        batch.records[0],
        page_number=7,
        record_index=19,
        source_digest=Sha256Digest("c" * 64),
    )

    second = service.normalize(replace(batch, records=(relocated,))).bars[0]

    assert second == first
    assert repository.history(first.key) == (first,)


def test_normalization_rejects_provider_identity_reuse_with_changed_content(
    tmp_path,
    make_provider_bar,
    fixed_instant,
    exchange_catalog,
    synthetic_provider_name,
    xnys,
    sample_symbol,
    mapped_instrument_repository,
) -> None:
    instruments, _ = mapped_instrument_repository
    batch = _accepted_batch(
        tmp_path,
        (make_provider_bar(provider_record_id="stable-provider-record"),),
        fixed_instant,
        exchange_catalog,
        synthetic_provider_name,
        xnys,
        sample_symbol,
    )
    repository = InMemoryPriceBarRepository()
    service = PriceBarNormalizationService(instruments, repository)
    service.normalize(batch)
    changed_record = replace(
        batch.records[0].record,
        high_price=batch.records[0].record.high_price + 1,
        close_price=batch.records[0].record.close_price + 1,
    )
    changed = replace(
        batch,
        records=(replace(batch.records[0], record=changed_record),),
    )

    with pytest.raises(DomainConflictError, match="reused a price-bar identity"):
        service.normalize(changed)
