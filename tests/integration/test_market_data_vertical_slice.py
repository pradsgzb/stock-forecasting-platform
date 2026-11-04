"""Production-path vertical slice from provider ingestion to point-in-time features."""

from datetime import date
from decimal import Decimal

import pytest

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.adapters.market_data.synthetic_provider import SyntheticMarketDataProvider
from stock_predictor.adapters.repositories.in_memory_feature_store import InMemoryFeatureStore
from stock_predictor.adapters.repositories.in_memory_price_bar_repository import (
    InMemoryAdjustmentFactorRepository,
    InMemoryPriceBarRepository,
)
from stock_predictor.adapters.repositories.in_memory_validation_repository import (
    InMemoryValidationReportRepository,
)
from stock_predictor.adapters.storage.local_ingestion_catalog import LocalIngestionCatalog
from stock_predictor.adapters.storage.local_raw_object_store import (
    LocalContentAddressedRawObjectStore,
)
from stock_predictor.application.features.calculators import (
    ClosePriceCalculator,
    SimpleReturnCalculator,
)
from stock_predictor.application.features.registry import FeatureCalculatorRegistry
from stock_predictor.application.features.service import FeaturePipeline
from stock_predictor.application.market_data.ingestion import MarketDataIngestionService
from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.application.normalization.service import PriceBarNormalizationService
from stock_predictor.application.point_in_time.service import PointInTimePriceService
from stock_predictor.application.quality.service import MarketDataQualityService
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.identifiers import FeatureSetVersionId
from stock_predictor.domain.market_data.contracts import PriceBarRequest
from stock_predictor.domain.market_data.features import FeatureSet

pytestmark = pytest.mark.integration


def test_ingest_validate_normalize_and_materialize_features(
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
    clock = FixedClock(fixed_instant)
    provider = SyntheticMarketDataProvider(
        (
            make_provider_bar(
                session_date=date(2025, 7, 1),
                open_price="99",
                high_price="101",
                low_price="98",
                close_price="100",
                provider_record_id="TEST-2025-07-01-r0",
            ),
            make_provider_bar(
                session_date=date(2025, 7, 2),
                open_price="101",
                high_price="104",
                low_price="100",
                close_price="103",
                provider_record_id="TEST-2025-07-02-r0",
            ),
        ),
        clock,
    )
    providers = MarketDataProviderRegistry((provider,))
    raw_objects = LocalContentAddressedRawObjectStore(tmp_path / "raw")
    catalog = LocalIngestionCatalog(tmp_path / "catalog")
    request = PriceBarRequest(
        provider=synthetic_provider_name,
        exchange_mic=xnys,
        symbols=(sample_symbol,),
        start=date(2025, 7, 1),
        end=date(2025, 7, 2),
        page_size=1,
    )

    ingestion = MarketDataIngestionService(providers, raw_objects, catalog, clock)
    manifest = ingestion.ingest_price_bars(request, idempotency_key="vertical-slice")
    assert len(manifest.pages) == 2
    assert ingestion.ingest_price_bars(
        request, idempotency_key="vertical-slice"
    ) == manifest

    calendars = ExchangeCalendarsProvider(exchange_catalog)
    reports = InMemoryValidationReportRepository()
    validated = MarketDataQualityService(
        providers,
        raw_objects,
        calendars,
        reports,
        clock,
    ).validate(manifest)
    validated.require_accepted()
    assert len(validated.records) == 2
    assert reports.latest_for_run(manifest.run_id) == validated.report

    bars = InMemoryPriceBarRepository()
    normalized = PriceBarNormalizationService(instruments, bars).normalize(validated)
    assert len(normalized.bars) == 2

    close = ClosePriceCalculator()
    one_session_return = SimpleReturnCalculator(1)
    feature_set = FeatureSet(
        feature_set_version_id=FeatureSetVersionId.new(),
        name="reference-eod",
        version="1.0.0",
        definitions=(close.definition, one_session_return.definition),
    )
    feature_store = InMemoryFeatureStore()
    pipeline = FeaturePipeline(
        FeatureCalculatorRegistry((close, one_session_return)),
        PointInTimePriceService(
            bars,
            InMemoryAdjustmentFactorRepository(),
            instruments,
            calendars,
        ),
        feature_store,
        clock,
    )

    snapshot = pipeline.materialize(
        feature_set,
        instrument.instrument_id,
        date(2025, 7, 2),
        fixed_instant,
        adjusted=False,
    )
    values = {item.definition.name: item.value for item in snapshot.observations}
    assert values == {
        "close_price": Decimal("103"),
        "simple_return_1s": Decimal("0.03"),
    }
    assert pipeline.materialize(
        feature_set,
        instrument.instrument_id,
        date(2025, 7, 2),
        fixed_instant,
        adjusted=False,
    ) == snapshot
