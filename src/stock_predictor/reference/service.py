"""Deterministic end-to-end reference scenario for research and paper evaluation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np

from stock_predictor.adapters.calendars.exchange_calendars_provider import (
    ExchangeCalendarsProvider,
)
from stock_predictor.adapters.market_data.synthetic_provider import SyntheticMarketDataProvider
from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.application.backtesting.engine import BacktestEngine
from stock_predictor.application.backtesting.policies import (
    BpsExecutionCostModel,
    TopKLongOnlyPolicy,
)
from stock_predictor.application.features.calculators import (
    ClosePriceCalculator,
    RollingVolatilityCalculator,
    SimpleMovingAverageCalculator,
    SimpleReturnCalculator,
)
from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.application.inference.service import BatchInferenceRequest
from stock_predictor.application.instruments.commands import AddSymbolMapping, RegisterInstrument
from stock_predictor.application.training.service import TrainingRequest
from stock_predictor.bootstrap.container import ApplicationContainer, build_container
from stock_predictor.bootstrap.settings import (
    ApplicationSettings,
    ContinuousTrainingSettings,
    DataQualitySettings,
    DatabaseSettings,
    ModelingSettings,
    MonitoringSettings,
    PlatformSettings,
    RuntimeEnvironment,
    StorageSettings,
)
from stock_predictor.domain.backtesting.models import (
    BacktestConfig,
    BacktestPriceBar,
    BacktestResult,
    ForecastSignal,
    PortfolioRiskLimits,
    TransactionCostSettings,
)
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.identifiers import (
    FeatureSetVersionId,
    ModelVersionId,
    MonitoringAlertId,
    SignalId,
    TargetDefinitionId,
)
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.temporal import (
    EffectivePeriod,
    HorizonUnit,
    InformationTimeline,
    InstantInterval,
    PredictionHorizon,
    UtcInstant,
)
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.market.identifiers import (
    MarketIdentifierCode,
    ProviderName,
    TickerSymbol,
)
from stock_predictor.domain.market.instrument import AssetClass
from stock_predictor.domain.market_data.contracts import (
    BarFrequency,
    PriceBarRequest,
    ProviderPriceBar,
    RecordOperation,
)
from stock_predictor.domain.market_data.features import FeatureSet
from stock_predictor.domain.mlops.continuous_training import RetrainingTrigger
from stock_predictor.domain.mlops.feedback import FeedbackMetric, FeedbackSummary
from stock_predictor.domain.mlops.monitoring import MonitoringAlert, MonitoringSeverity
from stock_predictor.domain.mlops.registry import (
    ApprovalDecision,
    ApprovalRole,
    GateResult,
    ModelApproval,
    ModelDeploymentScope,
    PromotionEvidence,
    RegistryAlias,
)
from stock_predictor.domain.modeling.datasets import (
    DatasetBuildPoint,
    DatasetBuildPolicy,
    DatasetSnapshot,
)
from stock_predictor.domain.modeling.evaluation import MetricDirection
from stock_predictor.domain.modeling.models import LearningTask, ModelFamily, ModelSpec
from stock_predictor.domain.modeling.splits import WalkForwardSplitConfig
from stock_predictor.domain.modeling.targets import TargetDefinition, TargetKind
from stock_predictor.domain.modeling.training import TrainingResult


class _ScenarioClock(Clock):
    """Mutable deterministic clock confined to the reference simulation."""

    __slots__ = ("_instant",)

    def __init__(self, instant: UtcInstant) -> None:
        self._instant = instant

    def now(self) -> UtcInstant:
        return self._instant

    def set(self, instant: UtcInstant) -> None:
        if instant < self._instant:
            raise ValueError("Reference scenario clock cannot move backward")
        self._instant = instant


@dataclass(frozen=True, slots=True)
class ReferenceScenarioReport:
    """Compact, serializable evidence emitted by the reference scenario."""

    schema_version: str
    generated_at: str
    raw_page_count: int
    validated_record_count: int
    normalized_bar_count: int
    dataset_row_count: int
    dataset_fingerprint: str
    selected_model_plugin: str
    model_version_id: str
    holdout_mae: str
    backtest_fingerprint: str
    backtest_trade_count: str
    prediction_count: int
    outcome_count: int
    feedback_mae: str
    performance_severity: str
    retraining_request_id: str
    challenger_model_version_id: str
    challenger_promoted: bool
    rollback_model_version_id: str
    final_champion_model_version_id: str
    paper_trading_only: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


class ReferenceScenarioService:
    """Runs Sections 06–20 together using deterministic synthetic market data."""

    __slots__ = ()

    def run(self, workspace: Path) -> ReferenceScenarioReport:
        workspace.mkdir(parents=True, exist_ok=True)
        mic = MarketIdentifierCode("XNYS")
        provider_name = ProviderName("synthetic")
        symbol = TickerSymbol("DEMO")
        currency = Currency("USD")
        settings = self._settings(workspace)
        bootstrap = build_container(settings)
        calendars = ExchangeCalendarsProvider(bootstrap.exchanges)
        sessions = calendars.sessions(mic, date(2025, 1, 2), date(2025, 5, 30))[:82]
        if len(sessions) < 60:
            raise RuntimeError("Reference scenario requires at least 60 exchange sessions")
        now = sessions[-1].closes_at.plus(timedelta(days=3))
        clock = _ScenarioClock(sessions[0].closes_at.plus(timedelta(minutes=4)))
        records = tuple(
            self._provider_bar(
                provider_name,
                symbol,
                mic,
                currency,
                item.session_date,
                item.closes_at,
                index,
            )
            for index, item in enumerate(sessions)
        )
        providers = MarketDataProviderRegistry(
            (SyntheticMarketDataProvider(records, clock),)
        )
        codec = TrustedJoblibArtifactCodec(allow_deserialization=True)
        container = build_container(
            settings,
            clock=clock,
            calendars=calendars,
            market_data_providers=providers,
            model_artifacts=codec,
        )
        instrument = container.instrument_service.register(
            RegisterInstrument(
                display_name="Reference Scenario Corporation",
                asset_class=AssetClass.EQUITY,
                primary_exchange_mic=mic,
                trading_currency=currency,
                listing_date=date(2020, 1, 2),
            )
        )
        container.instrument_service.add_symbol_mapping(
            AddSymbolMapping(
                instrument_id=instrument.instrument_id,
                provider=provider_name,
                symbol=symbol,
                exchange_mic=mic,
                effective_period=EffectivePeriod(date(2020, 1, 2)),
            )
        )
        raw_page_count = 0
        validated_record_count = 0
        normalized_bar_count = 0
        for index, session in enumerate(sessions):
            clock.set(session.closes_at.plus(timedelta(minutes=4)))
            daily_request = PriceBarRequest(
                provider=provider_name,
                exchange_mic=mic,
                symbols=(symbol,),
                start=session.session_date,
                end=session.session_date,
                page_size=1,
            )
            daily_manifest = container.ingestion_service.ingest_price_bars(
                daily_request,
                idempotency_key=f"reference-market-data-{index:03d}",
            )
            daily_validated = container.quality_service.validate(daily_manifest)
            daily_validated.require_accepted()
            daily_normalized = container.normalization_service.normalize(daily_validated)
            raw_page_count += len(daily_manifest.pages)
            validated_record_count += len(daily_validated.records)
            normalized_bar_count += len(daily_normalized.bars)
        clock.set(now)

        calculators = (
            ClosePriceCalculator(),
            SimpleReturnCalculator(1),
            SimpleMovingAverageCalculator(5),
            RollingVolatilityCalculator(5),
        )
        feature_set = FeatureSet(
            FeatureSetVersionId.new(),
            "reference-eod-features",
            "1.0.0",
            tuple(item.definition for item in calculators),
        )
        target = TargetDefinition(
            TargetDefinitionId.new(),
            "next_session_return",
            "1.0.0",
            TargetKind.SIMPLE_RETURN,
            PredictionHorizon(1, HorizonUnit.TRADING_SESSIONS),
        )
        points = tuple(
            DatasetBuildPoint(
                instrument_id=instrument.instrument_id,
                as_of=session.session_date,
                decision_cutoff=session.closes_at.plus(timedelta(minutes=5)),
                outcome_cutoff=sessions[index + 1].closes_at.plus(timedelta(minutes=5)),
            )
            for index, session in enumerate(sessions[6:-1], start=6)
        )
        dataset = container.dataset_builder.build(
            "reference-supervised-dataset",
            feature_set,
            target,
            points,
            DatasetBuildPolicy(adjusted_features=False),
        )
        split_plan = container.splitter.split(
            dataset,
            WalkForwardSplitConfig(
                minimum_train_periods=24,
                validation_periods=8,
                step_periods=8,
                final_holdout_periods=8,
                gap_periods=1,
                embargo_periods=1,
            ),
        )
        training_request = TrainingRequest(
            experiment_name="reference-end-to-end",
            dataset_version_id=dataset.dataset_version_id,
            split_plan=split_plan,
            candidates=(
                self._model_spec("zero", "baseline.zero_return", ModelFamily.BASELINE),
                self._model_spec(
                    "historical-mean",
                    "baseline.historical_mean",
                    ModelFamily.BASELINE,
                ),
                self._model_spec(
                    "ridge",
                    "linear.ridge",
                    ModelFamily.LINEAR,
                    alpha=Decimal("0.01"),
                ),
            ),
            primary_metric="mae",
            baseline_plugin_keys=(
                "baseline.zero_return",
                "baseline.historical_mean",
            ),
            intended_use="Deterministic reference scenario and paper evaluation.",
            prohibited_uses=("Live autonomous trading", "Investment advice"),
            limitations=("Synthetic prices do not represent market predictability.",),
        )
        result = container.training_service.train(training_request)
        backtest = self._backtest(
            container.backtest_engine,
            codec,
            result,
            dataset,
            split_plan.holdout_indices,
            container,
            currency,
        )
        scope = ModelDeploymentScope("staging", target.key, LearningTask.REGRESSION)
        evidence = self._promotion_evidence(
            now,
            dataset.fingerprint,
            backtest.fingerprint,
        )
        candidate = container.model_registry_service.register_candidate(
            result,
            scope,
            actor="reference-trainer",
        )
        validated_model, decision = container.model_registry_service.validate_candidate(
            candidate.model_version_id,
            evidence,
            actor="reference-validator",
        )
        if not decision.accepted:
            raise RuntimeError("Reference candidate unexpectedly failed validation")
        container.model_registry_service.stage(
            validated_model.model_version_id,
            actor="reference-release-manager",
        )
        container.model_registry_service.deploy_challenger(
            validated_model.model_version_id,
            actor="reference-release-manager",
            reason="reference shadow verification",
        )
        container.model_registry_service.promote_challenger(
            validated_model.model_version_id,
            evidence,
            actor="reference-deployment-approver",
            reason="reference initial champion",
        )
        prediction_dates = (sessions[-3], sessions[-2])
        predictions = []
        for index, session in enumerate(prediction_dates, 1):
            batch = container.inference_service.predict_batch(
                BatchInferenceRequest(
                    scope=scope,
                    target=target,
                    feature_set=feature_set,
                    instrument_ids=(instrument.instrument_id,),
                    as_of=session.session_date,
                    decision_cutoff=session.closes_at.plus(timedelta(minutes=5)),
                    idempotency_key=f"reference-inference-{index}",
                    adjusted=False,
                )
            )
            predictions.extend(batch.predictions)
        collection = container.outcome_collection_service.collect(target, now)
        feedback_now = now.plus(timedelta(minutes=1))
        clock.set(feedback_now)
        window = InstantInterval(now.plus(-timedelta(days=7)), feedback_now)
        feedback = container.feedback_service.summarize(
            result.model_version_id,
            target.key,
            window,
        )
        monitoring = container.monitoring_service.record_performance(feedback)

        challenger_request = TrainingRequest(
            experiment_name="reference-retraining",
            dataset_version_id=dataset.dataset_version_id,
            split_plan=split_plan,
            candidates=(
                self._model_spec("zero-v2", "baseline.zero_return", ModelFamily.BASELINE),
                self._model_spec(
                    "historical-mean-v2",
                    "baseline.historical_mean",
                    ModelFamily.BASELINE,
                ),
                self._model_spec(
                    "ridge-v2",
                    "linear.ridge",
                    ModelFamily.LINEAR,
                    alpha=Decimal("0.001"),
                ),
            ),
            primary_metric="mae",
            baseline_plugin_keys=(
                "baseline.zero_return",
                "baseline.historical_mean",
            ),
            intended_use="Controlled reference challenger.",
            prohibited_uses=("Live autonomous trading",),
            limitations=("Synthetic validation evidence only.",),
        )
        retraining = container.continuous_training_service.request_retraining(
            scope=scope,
            trigger=RetrainingTrigger.SCHEDULED,
            evidence_references=(monitoring.fingerprint,),
            requested_by="reference-monitor",
            idempotency_key="reference-retraining-v1",
        )
        challenger_evidence = self._promotion_evidence(
            feedback_now,
            dataset.fingerprint,
            backtest.fingerprint,
        )
        completed = container.continuous_training_service.run(
            retraining.request_id,
            challenger_request,
            challenger_evidence,
            actor="reference-ml-operator",
        )
        challenger_result = completed.training_result
        champion_summary = self._comparison_summary(
            result.model_version_id,
            target.key,
            window,
            Decimal("0.20"),
            feedback_now,
        )
        challenger_summary = self._comparison_summary(
            challenger_result.model_version_id,
            target.key,
            window,
            Decimal("0.10"),
            feedback_now,
        )
        comparison, deployment = container.continuous_training_service.compare_and_promote(
            scope=scope,
            champion_summary=champion_summary,
            challenger_summary=challenger_summary,
            metric_name="mae",
            direction=MetricDirection.MINIMIZE,
            promotion_evidence=challenger_evidence,
            actor="reference-deployment-approver",
            human_approved=True,
        )
        if not comparison.accepted or deployment is None:
            raise RuntimeError("Reference challenger unexpectedly failed promotion")
        critical = MonitoringAlert(
            alert_id=MonitoringAlertId.new(),
            model_version_id=challenger_result.model_version_id,
            severity=MonitoringSeverity.CRITICAL,
            category="reference_failure_injection",
            title="Reference rollback exercise",
            detail="Synthetic post-promotion degradation exceeded the rollback threshold.",
            evidence_reference="reference:rollback-injection",
            raised_at=feedback_now,
        )
        restored = container.continuous_training_service.rollback_on_alert(
            scope,
            critical,
            actor="reference-incident-commander",
        )
        final_champion = container.model_registry.resolve_alias(scope, RegistryAlias.CHAMPION)
        if final_champion is None:
            raise RuntimeError("Reference rollback left no champion")
        return ReferenceScenarioReport(
            schema_version="1.0.0",
            generated_at=feedback_now.isoformat(),
            raw_page_count=raw_page_count,
            validated_record_count=validated_record_count,
            normalized_bar_count=normalized_bar_count,
            dataset_row_count=dataset.row_count,
            dataset_fingerprint=dataset.fingerprint,
            selected_model_plugin=result.selected_spec.plugin_key,
            model_version_id=str(result.model_version_id),
            holdout_mae=str(result.holdout_report.metric("mae").value),
            backtest_fingerprint=backtest.fingerprint,
            backtest_trade_count=str(backtest.metric("trade_count").value),
            prediction_count=len(predictions),
            outcome_count=len(collection.collected),
            feedback_mae=str(feedback.metric("mae").value),
            performance_severity=monitoring.severity.name.lower(),
            retraining_request_id=str(retraining.request_id),
            challenger_model_version_id=str(challenger_result.model_version_id),
            challenger_promoted=deployment.model_version_id
            == challenger_result.model_version_id,
            rollback_model_version_id=str(restored.model_version_id),
            final_champion_model_version_id=str(final_champion.model_version_id),
            paper_trading_only=True,
        )

    @staticmethod
    def _settings(workspace: Path) -> PlatformSettings:
        return PlatformSettings(
            app=ApplicationSettings(environment=RuntimeEnvironment.TEST),
            storage=StorageSettings(data_root=workspace / "data"),
            database=DatabaseSettings(
                url=f"sqlite+pysqlite:///{workspace / 'operations.db'}"
            ),
            quality=DataQualitySettings(timeliness_warning_seconds=40_000_000),
            modeling=ModelingSettings(allow_trusted_model_deserialization=True),
            monitoring=MonitoringSettings(minimum_samples=2),
            continuous_training=ContinuousTrainingSettings(
                minimum_outcomes=2,
                minimum_improvement=Decimal("0.01"),
            ),
        )

    @staticmethod
    def _provider_bar(
        provider: ProviderName,
        symbol: TickerSymbol,
        mic: MarketIdentifierCode,
        currency: Currency,
        session_date: date,
        closes_at: UtcInstant,
        index: int,
    ) -> ProviderPriceBar:
        drift = Decimal(index) * Decimal("0.18")
        cycle = Decimal((index % 9) - 4) * Decimal("0.07")
        close = Decimal("100") + drift + cycle
        open_price = close - Decimal("0.15")
        timeline = InformationTimeline(
            event_time=closes_at,
            published_at=closes_at.plus(timedelta(minutes=1)),
            received_at=closes_at.plus(timedelta(minutes=2)),
            processed_at=closes_at.plus(timedelta(minutes=3)),
        )
        return ProviderPriceBar(
            provider_record_id=f"DEMO-{session_date.isoformat()}-r0",
            provider=provider,
            symbol=symbol,
            exchange_mic=mic,
            session_date=session_date,
            frequency=BarFrequency.DAILY,
            operation=RecordOperation.UPSERT,
            revision=0,
            currency=currency,
            timeline=timeline,
            open_price=open_price,
            high_price=close + Decimal("0.60"),
            low_price=open_price - Decimal("0.45"),
            close_price=close,
            volume=Decimal(100_000 + index * 750),
            metadata={"source": "reference-scenario"},
        )

    @staticmethod
    def _model_spec(
        name: str,
        plugin_key: str,
        family: ModelFamily,
        **parameters: Decimal,
    ) -> ModelSpec:
        return ModelSpec(
            name=name,
            version="1.0.0",
            family=family,
            task=LearningTask.REGRESSION,
            plugin_key=plugin_key,
            random_seed=17,
            hyperparameters=tuple(sorted(parameters.items())),
        )

    @staticmethod
    def _promotion_evidence(
        now: UtcInstant,
        dataset_fingerprint: str,
        backtest_fingerprint: str,
    ) -> PromotionEvidence:
        references = {
            "artifact_verified": "reference:artifact",
            "dataset_lineage_verified": dataset_fingerprint,
            "baseline_outperformed": "reference:baseline-comparison",
            "backtest_passed": backtest_fingerprint,
            "risk_limits_passed": "reference:risk-limits",
            "security_checks_passed": "reference:security-checks",
        }
        gates = tuple(
            GateResult(name, True, reference, f"{name} passed in the reference scenario")
            for name, reference in references.items()
        )
        approvals = tuple(
            ModelApproval(
                actor=f"reference-{role.value}",
                role=role,
                decision=ApprovalDecision.APPROVED,
                decided_at=now,
                comment="Reference evidence reviewed and approved.",
            )
            for role in ApprovalRole
        )
        return PromotionEvidence(gates, approvals, now)

    @staticmethod
    def _comparison_summary(
        model_version_id: ModelVersionId,
        target_key: str,
        window: InstantInterval,
        mae: Decimal,
        now: UtcInstant,
    ) -> FeedbackSummary:
        return FeedbackSummary(
            model_version_id=model_version_id,
            target_key=target_key,
            window=window,
            sample_count=2,
            metrics=(FeedbackMetric("mae", mae),),
            generated_at=now,
            outcome_fingerprints=("1" * 64, "2" * 64),
        )

    @staticmethod
    def _backtest(
        engine: BacktestEngine,
        codec: TrustedJoblibArtifactCodec,
        training_result: TrainingResult,
        dataset: DatasetSnapshot,
        holdout_indices: tuple[int, ...],
        container: ApplicationContainer,
        currency: Currency,
    ) -> BacktestResult:
        fitted = codec.deserialize(training_result.artifact)
        rows = tuple(dataset.rows[index] for index in holdout_indices)
        matrix = np.asarray(
            [[float(value) for value in row.feature_values] for row in rows],
            dtype=np.float64,
        )
        predicted = fitted.predict(matrix)
        signals: list[ForecastSignal] = []
        bars: list[BacktestPriceBar] = []
        for row, value in zip(rows, predicted, strict=True):
            instrument = container.instruments.get(row.instrument_id)
            execution = container.calendars.next_session(
                instrument.primary_exchange_mic,
                row.as_of,
            )
            path = container.point_in_time_price_service.price_path(
                row.instrument_id,
                execution.session_date,
                execution.session_date,
                dataset.created_at,
                adjusted=False,
            )
            if len(path) != 1:
                raise RuntimeError("Reference backtest execution price is unavailable")
            source = path[0]
            signals.append(
                ForecastSignal(
                    signal_id=SignalId.new(),
                    instrument_id=row.instrument_id,
                    model_version_id=training_result.model_version_id,
                    as_of=row.as_of,
                    generated_at=row.decision_cutoff,
                    expected_return=Decimal(format(float(value), ".15g")),
                )
            )
            bars.append(
                BacktestPriceBar(
                    instrument_id=row.instrument_id,
                    session_date=execution.session_date,
                    opens_at=execution.opens_at,
                    closes_at=execution.closes_at,
                    open_price=Price(source.open_price, currency),
                    high_price=Price(source.high_price, currency),
                    low_price=Price(source.low_price, currency),
                    close_price=Price(source.close_price, currency),
                    volume=Quantity(source.volume),
                    source_fingerprint=source.source_fingerprint,
                )
            )
        return engine.run(
            tuple(bars),
            tuple(signals),
            BacktestConfig(
                name="reference-paper-backtest",
                initial_cash=Money("100000", currency),
                costs=TransactionCostSettings(
                    commission_bps="1",
                    slippage_bps="2",
                    half_spread_bps="1",
                    fixed_commission="0.50",
                    maximum_volume_participation="0.05",
                ),
                risk_limits=PortfolioRiskLimits(
                    maximum_position_weight="0.50",
                    maximum_gross_exposure="0.50",
                    maximum_rebalance_turnover="1",
                    maximum_drawdown="0.25",
                    top_k=1,
                ),
            ),
        )
