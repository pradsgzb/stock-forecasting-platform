"""Manual composition root for process dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.adapters.experiments.local_jsonl_tracker import (
    LocalJsonlExperimentTracker,
)
from stock_predictor.adapters.events.in_memory_publisher import InMemoryEventPublisher
from stock_predictor.adapters.market_data.synthetic_provider import SyntheticMarketDataProvider
from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.adapters.observability.prometheus_telemetry import (
    PrometheusTelemetry,
)
from stock_predictor.adapters.persistence.sqlalchemy_store import (
    SqlAlchemyOperationalStore,
)
from stock_predictor.adapters.models.baselines import (
    FeatureEchoRegressorPlugin,
    HistoricalMeanRegressorPlugin,
    LogisticRegressionPlugin,
    MajorityClassifierPlugin,
    RandomForestClassifierPlugin,
    RandomForestRegressorPlugin,
    RidgeRegressionPlugin,
    ZeroReturnRegressorPlugin,
)
from stock_predictor.adapters.repositories.in_memory_dataset_repository import (
    InMemoryDatasetRepository,
)
from stock_predictor.adapters.repositories.in_memory_feature_store import InMemoryFeatureStore
from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
    InMemoryInstrumentRepository,
)
from stock_predictor.adapters.repositories.in_memory_model_registry import (
    InMemoryModelRegistryRepository,
)
from stock_predictor.adapters.repositories.in_memory_monitoring_repository import (
    InMemoryMonitoringRepository,
)
from stock_predictor.adapters.repositories.in_memory_outcome_repository import (
    InMemoryOutcomeRepository,
)
from stock_predictor.adapters.repositories.in_memory_prediction_ledger import (
    InMemoryPredictionLedger,
)
from stock_predictor.adapters.repositories.in_memory_price_bar_repository import (
    InMemoryAdjustmentFactorRepository,
    InMemoryPriceBarRepository,
)
from stock_predictor.adapters.repositories.in_memory_retraining_repository import (
    InMemoryRetrainingRepository,
)
from stock_predictor.adapters.repositories.in_memory_validation_repository import (
    InMemoryValidationReportRepository,
)
from stock_predictor.adapters.storage.local_ingestion_catalog import LocalIngestionCatalog
from stock_predictor.adapters.storage.local_raw_object_store import (
    LocalContentAddressedRawObjectStore,
)
from stock_predictor.application.backtesting.engine import BacktestEngine
from stock_predictor.application.backtesting.policies import (
    BpsExecutionCostModel,
    TopKLongOnlyPolicy,
)
from stock_predictor.application.continuous_training.service import (
    ContinuousTrainingService,
)
from stock_predictor.application.datasets.service import DatasetBuilder
from stock_predictor.application.evaluation.service import ModelEvaluationService
from stock_predictor.application.features.calculators import (
    ClosePriceCalculator,
    RollingVolatilityCalculator,
    SimpleMovingAverageCalculator,
    SimpleReturnCalculator,
    VolumeRatioCalculator,
)
from stock_predictor.application.features.registry import FeatureCalculatorRegistry
from stock_predictor.application.features.service import FeaturePipeline
from stock_predictor.application.feedback.service import (
    FeedbackService,
    OutcomeCollectionService,
)
from stock_predictor.application.health.service import HealthService
from stock_predictor.application.inference.service import ModelInferenceService
from stock_predictor.application.instruments.service import InstrumentMasterService
from stock_predictor.application.labels.service import TargetLabelService
from stock_predictor.application.market_data.ingestion import (
    IngestionPolicy,
    MarketDataIngestionService,
)
from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.application.market_time.service import MarketTimeService
from stock_predictor.application.models.registry import ModelPluginRegistry
from stock_predictor.application.monitoring.service import (
    DriftPolicy,
    ModelMonitoringService,
    PerformancePolicy,
)
from stock_predictor.application.normalization.service import PriceBarNormalizationService
from stock_predictor.application.observability.slo import SloEvaluationService
from stock_predictor.application.operations.outbox import OutboxDispatcher
from stock_predictor.application.paper_trading.service import (
    PaperTradingPolicy,
    PaperTradingService,
)
from stock_predictor.application.point_in_time.service import PointInTimePriceService
from stock_predictor.application.quality.service import (
    MarketDataQualityService,
    ValidationPolicy,
)
from stock_predictor.application.registry.service import ModelRegistryService
from stock_predictor.application.splitting.service import PurgedWalkForwardSplitter
from stock_predictor.application.training.service import ModelTrainingService
from stock_predictor.bootstrap.secrets import SecretProvider, build_secret_provider
from stock_predictor.bootstrap.settings import PlatformSettings
from stock_predictor.domain.common.clock import Clock, SystemClock
from stock_predictor.domain.market.exchange import Exchange, ExchangeCatalog
from stock_predictor.domain.market.identifiers import CountryCode, MarketIdentifierCode
from stock_predictor.domain.mlops.registry import ApprovalRole, PromotionPolicy
from stock_predictor.ports.calendar_provider import CalendarProvider
from stock_predictor.ports.dataset_repository import DatasetRepository
from stock_predictor.ports.event_publisher import EventPublisher
from stock_predictor.ports.experiment_tracker import ExperimentTracker
from stock_predictor.ports.feature_store import FeatureStore
from stock_predictor.ports.ingestion_catalog import IngestionCatalog
from stock_predictor.ports.instrument_repository import InstrumentRepository
from stock_predictor.ports.model_plugin import ModelArtifactCodec
from stock_predictor.ports.model_registry import ModelRegistryRepository
from stock_predictor.ports.monitoring_repository import MonitoringRepository
from stock_predictor.ports.operational_store import OperationalUnitOfWorkFactory
from stock_predictor.ports.outcome_repository import OutcomeRepository
from stock_predictor.ports.prediction_ledger import PredictionLedger
from stock_predictor.ports.price_bar_repository import (
    AdjustmentFactorRepository,
    PriceBarRepository,
)
from stock_predictor.ports.raw_object_store import RawObjectStore
from stock_predictor.ports.retraining_repository import RetrainingRepository
from stock_predictor.ports.telemetry import Telemetry
from stock_predictor.ports.validation_report_repository import ValidationReportRepository


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """Concrete dependency graph for one process, passed explicitly."""

    settings: PlatformSettings
    clock: Clock
    exchanges: ExchangeCatalog
    calendars: CalendarProvider
    instruments: InstrumentRepository
    secrets: SecretProvider
    raw_objects: RawObjectStore
    ingestion_catalog: IngestionCatalog
    validation_reports: ValidationReportRepository
    price_bars: PriceBarRepository
    adjustment_factors: AdjustmentFactorRepository
    feature_store: FeatureStore
    datasets: DatasetRepository
    experiments: ExperimentTracker
    model_artifacts: ModelArtifactCodec
    model_registry: ModelRegistryRepository
    prediction_ledger: PredictionLedger
    outcomes: OutcomeRepository
    monitoring: MonitoringRepository
    retraining_requests: RetrainingRepository
    operational_store: OperationalUnitOfWorkFactory
    telemetry: Telemetry
    event_publisher: EventPublisher
    market_data_providers: MarketDataProviderRegistry
    feature_calculators: FeatureCalculatorRegistry
    model_plugins: ModelPluginRegistry
    instrument_service: InstrumentMasterService
    market_time_service: MarketTimeService
    ingestion_service: MarketDataIngestionService
    quality_service: MarketDataQualityService
    normalization_service: PriceBarNormalizationService
    point_in_time_price_service: PointInTimePriceService
    feature_pipeline: FeaturePipeline
    target_label_service: TargetLabelService
    dataset_builder: DatasetBuilder
    splitter: PurgedWalkForwardSplitter
    evaluator: ModelEvaluationService
    training_service: ModelTrainingService
    backtest_engine: BacktestEngine
    model_registry_service: ModelRegistryService
    inference_service: ModelInferenceService
    outcome_collection_service: OutcomeCollectionService
    feedback_service: FeedbackService
    monitoring_service: ModelMonitoringService
    continuous_training_service: ContinuousTrainingService
    paper_trading_service: PaperTradingService
    health_service: HealthService
    slo_service: SloEvaluationService
    outbox_dispatcher: OutboxDispatcher


def _build_exchange_catalog(settings: PlatformSettings) -> ExchangeCatalog:
    exchanges = tuple(
        Exchange(
            mic=MarketIdentifierCode(item.mic),
            name=item.name,
            country_code=CountryCode(item.country_code),
            timezone_name=item.timezone_name,
            calendar_name=item.calendar_name,
        )
        for item in settings.market.exchanges
    )
    return ExchangeCatalog(exchanges)


def _default_model_plugins() -> ModelPluginRegistry:
    return ModelPluginRegistry(
        (
            ZeroReturnRegressorPlugin(),
            HistoricalMeanRegressorPlugin(),
            MajorityClassifierPlugin(),
            FeatureEchoRegressorPlugin(),
            RidgeRegressionPlugin(),
            LogisticRegressionPlugin(),
            RandomForestRegressorPlugin(),
            RandomForestClassifierPlugin(),
        )
    )


def build_container(
    settings: PlatformSettings,
    *,
    clock: Clock | None = None,
    instruments: InstrumentRepository | None = None,
    calendars: CalendarProvider | None = None,
    secrets: SecretProvider | None = None,
    raw_objects: RawObjectStore | None = None,
    ingestion_catalog: IngestionCatalog | None = None,
    validation_reports: ValidationReportRepository | None = None,
    price_bars: PriceBarRepository | None = None,
    adjustment_factors: AdjustmentFactorRepository | None = None,
    feature_store: FeatureStore | None = None,
    datasets: DatasetRepository | None = None,
    experiments: ExperimentTracker | None = None,
    model_artifacts: ModelArtifactCodec | None = None,
    model_registry: ModelRegistryRepository | None = None,
    prediction_ledger: PredictionLedger | None = None,
    outcomes: OutcomeRepository | None = None,
    monitoring: MonitoringRepository | None = None,
    retraining_requests: RetrainingRepository | None = None,
    operational_store: OperationalUnitOfWorkFactory | None = None,
    telemetry: Telemetry | None = None,
    event_publisher: EventPublisher | None = None,
    market_data_providers: MarketDataProviderRegistry | None = None,
    feature_calculators: FeatureCalculatorRegistry | None = None,
    model_plugins: ModelPluginRegistry | None = None,
) -> ApplicationContainer:
    """Construct a dependency graph, allowing explicit test substitutions."""
    resolved_clock = clock or SystemClock()
    exchange_catalog = _build_exchange_catalog(settings)
    resolved_instruments = instruments or InMemoryInstrumentRepository()
    resolved_calendars = calendars or ExchangeCalendarsProvider(exchange_catalog)
    resolved_secrets = secrets or build_secret_provider(settings.security)
    resolved_raw_objects = raw_objects or LocalContentAddressedRawObjectStore(
        settings.storage.data_root / settings.storage.raw_objects_subdirectory
    )
    resolved_ingestion_catalog = ingestion_catalog or LocalIngestionCatalog(
        settings.storage.data_root / settings.storage.ingestion_catalog_subdirectory
    )
    resolved_validation_reports = validation_reports or InMemoryValidationReportRepository()
    resolved_price_bars = price_bars or InMemoryPriceBarRepository()
    resolved_adjustments = adjustment_factors or InMemoryAdjustmentFactorRepository()
    resolved_feature_store = feature_store or InMemoryFeatureStore()
    resolved_datasets = datasets or InMemoryDatasetRepository()
    resolved_experiments = experiments or LocalJsonlExperimentTracker(
        settings.storage.data_root / settings.storage.experiment_events_subdirectory
    )
    resolved_artifacts = model_artifacts or TrustedJoblibArtifactCodec(
        allow_deserialization=settings.modeling.allow_trusted_model_deserialization
    )
    resolved_registry = model_registry or InMemoryModelRegistryRepository()
    resolved_ledger = prediction_ledger or InMemoryPredictionLedger()
    resolved_outcomes = outcomes or InMemoryOutcomeRepository()
    resolved_monitoring = monitoring or InMemoryMonitoringRepository()
    resolved_retraining = retraining_requests or InMemoryRetrainingRepository()
    resolved_operational_store = operational_store or SqlAlchemyOperationalStore(
        settings.database.url,
        echo=settings.database.echo,
        pool_pre_ping=settings.database.pool_pre_ping,
    )
    resolved_telemetry = telemetry or PrometheusTelemetry(
        namespace=settings.observability.metrics_namespace
    )
    resolved_publisher = event_publisher or InMemoryEventPublisher()
    resolved_providers = market_data_providers or MarketDataProviderRegistry(
        (SyntheticMarketDataProvider((), resolved_clock),)
    )
    resolved_calculators = feature_calculators or FeatureCalculatorRegistry(
        (
            ClosePriceCalculator(),
            SimpleReturnCalculator(1),
            SimpleReturnCalculator(5),
            SimpleMovingAverageCalculator(5),
            RollingVolatilityCalculator(5),
            VolumeRatioCalculator(5),
        )
    )
    resolved_model_plugins = model_plugins or _default_model_plugins()
    point_in_time_service = PointInTimePriceService(
        resolved_price_bars,
        resolved_adjustments,
        resolved_instruments,
        resolved_calendars,
    )
    feature_pipeline = FeaturePipeline(
        resolved_calculators,
        point_in_time_service,
        resolved_feature_store,
        resolved_clock,
    )
    target_label_service = TargetLabelService(
        point_in_time_service,
        resolved_instruments,
        resolved_calendars,
    )
    evaluator = ModelEvaluationService(resolved_clock)
    training_service = ModelTrainingService(
        resolved_datasets,
        resolved_model_plugins,
        evaluator,
        resolved_artifacts,
        resolved_experiments,
        resolved_clock,
    )
    registry_service = ModelRegistryService(
        resolved_registry,
        resolved_clock,
        PromotionPolicy(
            required_gate_names=settings.model_registry.required_gate_names,
            required_approval_roles=tuple(
                ApprovalRole(item)
                for item in settings.model_registry.required_approval_roles
            ),
        ),
    )
    inference_service = ModelInferenceService(
        resolved_registry,
        resolved_artifacts,
        feature_pipeline,
        resolved_ledger,
        resolved_clock,
        maximum_batch_size=settings.inference.maximum_batch_size,
        allow_online=settings.features.enable_future_online_inference,
    )
    feedback_service = FeedbackService(resolved_outcomes, resolved_clock)
    monitoring_service = ModelMonitoringService(
        resolved_monitoring,
        resolved_clock,
        drift_policy=DriftPolicy(
            minimum_samples=settings.monitoring.minimum_samples,
            histogram_bins=settings.monitoring.histogram_bins,
            psi_warning=settings.monitoring.psi_warning,
            psi_critical=settings.monitoring.psi_critical,
            mean_shift_warning=settings.monitoring.mean_shift_warning,
            mean_shift_critical=settings.monitoring.mean_shift_critical,
            missing_delta_warning=settings.monitoring.missing_delta_warning,
            missing_delta_critical=settings.monitoring.missing_delta_critical,
            js_warning=settings.monitoring.js_warning,
            js_critical=settings.monitoring.js_critical,
        ),
        performance_policy=PerformancePolicy(
            minimum_samples=settings.monitoring.minimum_samples,
            degradation_warning=(
                settings.monitoring.performance_degradation_warning
            ),
            degradation_critical=(
                settings.monitoring.performance_degradation_critical
            ),
            directional_accuracy_warning=(
                settings.monitoring.directional_accuracy_warning
            ),
            directional_accuracy_critical=(
                settings.monitoring.directional_accuracy_critical
            ),
        ),
    )
    continuous_training_service = ContinuousTrainingService(
        resolved_retraining,
        training_service,
        registry_service,
        resolved_registry,
        resolved_clock,
        minimum_outcomes=settings.continuous_training.minimum_outcomes,
        minimum_improvement=settings.continuous_training.minimum_improvement,
        allow_automatic_promotion=(
            settings.continuous_training.allow_automatic_promotion
        ),
    )
    paper_trading_service = PaperTradingService(
        resolved_operational_store,
        resolved_clock,
        resolved_telemetry,
        policy=PaperTradingPolicy(
            spread_bps=settings.paper_trading.spread_bps,
            slippage_bps=settings.paper_trading.slippage_bps,
            commission_bps=settings.paper_trading.commission_bps,
            fixed_commission=settings.paper_trading.fixed_commission,
            maximum_order_notional=settings.paper_trading.maximum_order_notional,
            maximum_position_notional=(
                settings.paper_trading.maximum_position_notional
            ),
            maximum_price_age=timedelta(
                seconds=settings.paper_trading.maximum_price_age_seconds
            ),
            idempotency_ttl=timedelta(
                seconds=settings.paper_trading.idempotency_ttl_seconds
            ),
        ),
    )
    health_service = HealthService(
        resolved_operational_store,
        resolved_clock,
        resolved_telemetry,
    )
    slo_service = SloEvaluationService(resolved_operational_store, resolved_clock)
    outbox_dispatcher = OutboxDispatcher(
        resolved_operational_store,
        resolved_publisher,
        resolved_clock,
    )
    return ApplicationContainer(
        settings=settings,
        clock=resolved_clock,
        exchanges=exchange_catalog,
        calendars=resolved_calendars,
        instruments=resolved_instruments,
        secrets=resolved_secrets,
        raw_objects=resolved_raw_objects,
        ingestion_catalog=resolved_ingestion_catalog,
        validation_reports=resolved_validation_reports,
        price_bars=resolved_price_bars,
        adjustment_factors=resolved_adjustments,
        feature_store=resolved_feature_store,
        datasets=resolved_datasets,
        experiments=resolved_experiments,
        model_artifacts=resolved_artifacts,
        model_registry=resolved_registry,
        prediction_ledger=resolved_ledger,
        outcomes=resolved_outcomes,
        monitoring=resolved_monitoring,
        retraining_requests=resolved_retraining,
        operational_store=resolved_operational_store,
        telemetry=resolved_telemetry,
        event_publisher=resolved_publisher,
        market_data_providers=resolved_providers,
        feature_calculators=resolved_calculators,
        model_plugins=resolved_model_plugins,
        instrument_service=InstrumentMasterService(resolved_instruments, exchange_catalog),
        market_time_service=MarketTimeService(resolved_calendars, exchange_catalog),
        ingestion_service=MarketDataIngestionService(
            resolved_providers,
            resolved_raw_objects,
            resolved_ingestion_catalog,
            resolved_clock,
            IngestionPolicy(
                maximum_pages=settings.ingestion.maximum_pages,
                maximum_page_bytes=settings.ingestion.maximum_page_bytes,
            ),
        ),
        quality_service=MarketDataQualityService(
            resolved_providers,
            resolved_raw_objects,
            resolved_calendars,
            resolved_validation_reports,
            resolved_clock,
            policy=ValidationPolicy(
                rule_set_version=settings.quality.rule_set_version,
                minimum_acceptable_score=settings.quality.minimum_acceptable_score,
                timeliness_warning_after=settings.quality.timeliness_warning_after,
            ),
        ),
        normalization_service=PriceBarNormalizationService(
            resolved_instruments,
            resolved_price_bars,
        ),
        point_in_time_price_service=point_in_time_service,
        feature_pipeline=feature_pipeline,
        target_label_service=target_label_service,
        dataset_builder=DatasetBuilder(
            feature_pipeline,
            target_label_service,
            resolved_datasets,
            resolved_clock,
        ),
        splitter=PurgedWalkForwardSplitter(),
        evaluator=evaluator,
        training_service=training_service,
        backtest_engine=BacktestEngine(
            TopKLongOnlyPolicy(),
            BpsExecutionCostModel(),
        ),
        model_registry_service=registry_service,
        inference_service=inference_service,
        outcome_collection_service=OutcomeCollectionService(
            resolved_ledger,
            resolved_outcomes,
            target_label_service,
            resolved_clock,
        ),
        feedback_service=feedback_service,
        monitoring_service=monitoring_service,
        continuous_training_service=continuous_training_service,
        paper_trading_service=paper_trading_service,
        health_service=health_service,
        slo_service=slo_service,
        outbox_dispatcher=outbox_dispatcher,
    )
