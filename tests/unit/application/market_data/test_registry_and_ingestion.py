from datetime import date
from pathlib import Path

import pytest

from stock_predictor.adapters.market_data.synthetic_provider import SyntheticMarketDataProvider
from stock_predictor.adapters.repositories.in_memory_ingestion_catalog import (
    InMemoryIngestionCatalog,
)
from stock_predictor.adapters.storage.local_raw_object_store import (
    LocalContentAddressedRawObjectStore,
)
from stock_predictor.application.market_data.ingestion import (
    IngestionPolicy,
    MarketDataIngestionService,
)
from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
)
from stock_predictor.domain.market.identifiers import TickerSymbol
from stock_predictor.domain.market_data.contracts import MarketDataPage, PriceBarRequest
from stock_predictor.ports.market_data_provider import TransientMarketDataProviderError


class FlakyProvider:
    def __init__(self, delegate):
        self.delegate = delegate
        self.failed = False

    @property
    def capabilities(self):
        return self.delegate.capabilities

    def fetch_price_bars(self, request, *, cursor=None):
        if cursor == "1" and not self.failed:
            self.failed = True
            raise TransientMarketDataProviderError("simulated outage")
        return self.delegate.fetch_price_bars(request, cursor=cursor)

    def decode_price_bars(self, page):
        return self.delegate.decode_price_bars(page)


class LoopingProvider:
    def __init__(self, delegate):
        self.delegate = delegate

    @property
    def capabilities(self):
        return self.delegate.capabilities

    def fetch_price_bars(self, request, *, cursor=None):
        page = self.delegate.fetch_price_bars(request, cursor=None)
        return MarketDataPage(
            page.provider,
            page.request_fingerprint,
            page.provider_request_id,
            page.retrieved_at,
            page.schema_version,
            page.content_type,
            page.raw_payload,
            "loop",
            page.advertised_record_count,
        )

    def decode_price_bars(self, page):
        return self.delegate.decode_price_bars(page)


def _request(provider, xnys, sample_symbol, *, page_size=1, end=date(2025, 7, 2)):
    return PriceBarRequest(
        provider,
        xnys,
        (sample_symbol,),
        date(2025, 7, 1),
        end,
        page_size=page_size,
    )


def test_registry_rejects_duplicates_and_unknown_provider(
    make_provider_bar, fixed_instant
) -> None:
    provider = SyntheticMarketDataProvider(
        (make_provider_bar(),), FixedClock(fixed_instant)
    )
    registry = MarketDataProviderRegistry((provider,))
    with pytest.raises(DomainConflictError, match="already registered"):
        registry.register(provider)
    with pytest.raises(DomainNotFoundError, match="not registered"):
        from stock_predictor.domain.market.identifiers import ProviderName

        registry.get(ProviderName("missing"))


def test_ingestion_persists_pages_and_is_idempotent(
    tmp_path: Path,
    make_provider_bar,
    fixed_instant,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    records = (
        make_provider_bar(date(2025, 7, 1)),
        make_provider_bar(date(2025, 7, 2)),
    )
    clock = FixedClock(fixed_instant)
    provider = SyntheticMarketDataProvider(records, clock)
    catalog = InMemoryIngestionCatalog()
    store = LocalContentAddressedRawObjectStore(tmp_path)
    service = MarketDataIngestionService(
        MarketDataProviderRegistry((provider,)), store, catalog, clock
    )
    request = _request(synthetic_provider_name, xnys, sample_symbol)

    first = service.ingest_price_bars(request)
    second = service.ingest_price_bars(request)

    assert first == second
    assert len(first.pages) == 2
    assert all(store.exists(item.raw_object.digest) for item in first.pages)
    assert catalog.load_checkpoint(request.request_fingerprint) is None


def test_ingestion_resumes_from_saved_checkpoint(
    tmp_path: Path,
    make_provider_bar,
    fixed_instant,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    records = (
        make_provider_bar(date(2025, 7, 1)),
        make_provider_bar(date(2025, 7, 2)),
    )
    clock = FixedClock(fixed_instant)
    delegate = SyntheticMarketDataProvider(records, clock)
    flaky = FlakyProvider(delegate)
    catalog = InMemoryIngestionCatalog()
    service = MarketDataIngestionService(
        MarketDataProviderRegistry((flaky,)),
        LocalContentAddressedRawObjectStore(tmp_path),
        catalog,
        clock,
    )
    request = _request(synthetic_provider_name, xnys, sample_symbol)

    with pytest.raises(TransientMarketDataProviderError):
        service.ingest_price_bars(request, idempotency_key="resume")
    checkpoint = catalog.load_checkpoint("resume")
    assert checkpoint is not None
    assert checkpoint.next_page_number == 2

    manifest = service.ingest_price_bars(request, idempotency_key="resume")
    assert len(manifest.pages) == 2
    assert manifest.pages[0] == checkpoint.completed_pages[0]


def test_idempotency_key_cannot_be_reused_for_another_request(
    tmp_path: Path,
    make_provider_bar,
    fixed_instant,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    clock = FixedClock(fixed_instant)
    provider = SyntheticMarketDataProvider((make_provider_bar(),), clock)
    service = MarketDataIngestionService(
        MarketDataProviderRegistry((provider,)),
        LocalContentAddressedRawObjectStore(tmp_path),
        InMemoryIngestionCatalog(),
        clock,
    )
    service.ingest_price_bars(
        _request(synthetic_provider_name, xnys, sample_symbol), idempotency_key="same"
    )
    with pytest.raises(DomainConflictError, match="different request"):
        service.ingest_price_bars(
            _request(
                synthetic_provider_name,
                xnys,
                sample_symbol,
                end=date(2025, 7, 3),
            ),
            idempotency_key="same",
        )


def test_ingestion_enforces_page_and_payload_limits(
    tmp_path: Path,
    make_provider_bar,
    fixed_instant,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    records = (
        make_provider_bar(date(2025, 7, 1)),
        make_provider_bar(date(2025, 7, 2)),
    )
    clock = FixedClock(fixed_instant)
    provider = SyntheticMarketDataProvider(records, clock)
    request = _request(synthetic_provider_name, xnys, sample_symbol)

    page_limited = MarketDataIngestionService(
        MarketDataProviderRegistry((provider,)),
        LocalContentAddressedRawObjectStore(tmp_path / "pages"),
        InMemoryIngestionCatalog(),
        clock,
        IngestionPolicy(maximum_pages=1),
    )
    with pytest.raises(DomainValidationError, match="page limit"):
        page_limited.ingest_price_bars(request)

    byte_limited = MarketDataIngestionService(
        MarketDataProviderRegistry((provider,)),
        LocalContentAddressedRawObjectStore(tmp_path / "bytes"),
        InMemoryIngestionCatalog(),
        clock,
        IngestionPolicy(maximum_page_bytes=1),
    )
    with pytest.raises(DomainValidationError, match="byte limit"):
        byte_limited.ingest_price_bars(request)


def test_ingestion_rejects_non_progressing_cursor(
    tmp_path: Path,
    make_provider_bar,
    fixed_instant,
    synthetic_provider_name,
    xnys,
    sample_symbol,
) -> None:
    clock = FixedClock(fixed_instant)
    delegate = SyntheticMarketDataProvider((make_provider_bar(),), clock)
    provider = LoopingProvider(delegate)
    service = MarketDataIngestionService(
        MarketDataProviderRegistry((provider,)),
        LocalContentAddressedRawObjectStore(tmp_path),
        InMemoryIngestionCatalog(),
        clock,
    )

    with pytest.raises(DomainValidationError, match="forward progress"):
        service.ingest_price_bars(
            _request(synthetic_provider_name, xnys, sample_symbol)
        )
