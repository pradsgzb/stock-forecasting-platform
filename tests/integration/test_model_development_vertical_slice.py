"""End-to-end research slice from immutable dataset to paper backtest evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from stock_predictor.adapters.experiments.in_memory_tracker import (
    InMemoryExperimentTracker,
)
from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.adapters.models.baselines import (
    HistoricalMeanRegressorPlugin,
    RidgeRegressionPlugin,
    ZeroReturnRegressorPlugin,
)
from stock_predictor.adapters.repositories.in_memory_dataset_repository import (
    InMemoryDatasetRepository,
)
from stock_predictor.application.backtesting.engine import BacktestEngine
from stock_predictor.application.backtesting.policies import (
    BpsExecutionCostModel,
    TopKLongOnlyPolicy,
)
from stock_predictor.application.evaluation.service import ModelEvaluationService
from stock_predictor.application.models.registry import ModelPluginRegistry
from stock_predictor.application.splitting.service import PurgedWalkForwardSplitter
from stock_predictor.application.training.service import (
    ModelTrainingService,
    TrainingRequest,
)
from stock_predictor.domain.backtesting.models import (
    BacktestConfig,
    BacktestPriceBar,
    ForecastSignal,
    PortfolioRiskLimits,
    TransactionCostSettings,
)
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.identifiers import SignalId
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelFamily,
    ModelSpec,
)
from stock_predictor.domain.modeling.splits import WalkForwardSplitConfig
from tests.helpers.modeling import make_dataset

pytestmark = pytest.mark.integration


def _spec(name: str, plugin_key: str, **parameters: Decimal) -> ModelSpec:
    return ModelSpec(
        name=name,
        version="1.0.0",
        family=(
            ModelFamily.LINEAR
            if plugin_key.startswith("linear")
            else ModelFamily.BASELINE
        ),
        task=LearningTask.REGRESSION,
        plugin_key=plugin_key,
        random_seed=17,
        hyperparameters=tuple(sorted(parameters.items())),
    )


def test_train_load_predict_and_backtest_without_touching_live_trading() -> None:
    dataset = make_dataset(periods=32)
    repository = InMemoryDatasetRepository()
    repository.put(dataset)
    split_plan = PurgedWalkForwardSplitter().split(
        dataset,
        WalkForwardSplitConfig(
            minimum_train_periods=8,
            validation_periods=4,
            step_periods=4,
            final_holdout_periods=4,
            gap_periods=1,
        ),
    )
    clock = FixedClock(UtcInstant(datetime(2026, 2, 1, tzinfo=UTC)))
    codec = TrustedJoblibArtifactCodec(allow_deserialization=True)
    training = ModelTrainingService(
        repository,
        ModelPluginRegistry(
            (
                ZeroReturnRegressorPlugin(),
                HistoricalMeanRegressorPlugin(),
                RidgeRegressionPlugin(),
            )
        ),
        ModelEvaluationService(clock),
        codec,
        InMemoryExperimentTracker(),
        clock,
    )
    result = training.train(
        TrainingRequest(
            experiment_name="reference-research-slice",
            dataset_version_id=dataset.dataset_version_id,
            split_plan=split_plan,
            candidates=(
                _spec("zero", "baseline.zero_return"),
                _spec("mean", "baseline.historical_mean"),
                _spec("ridge", "linear.ridge", alpha=Decimal("0.001")),
            ),
            primary_metric="mae",
            baseline_plugin_keys=(
                "baseline.zero_return",
                "baseline.historical_mean",
            ),
        )
    )
    fitted = codec.deserialize(result.artifact)
    holdout_rows = tuple(dataset.rows[index] for index in split_plan.holdout_indices)
    matrix = np.asarray(
        [[float(value) for value in row.feature_values] for row in holdout_rows],
        dtype=np.float64,
    )
    predictions = fitted.predict(matrix)

    currency = Currency("USD")
    instrument_id = holdout_rows[0].instrument_id
    signals: list[ForecastSignal] = []
    bars: list[BacktestPriceBar] = []
    for index, (row, prediction) in enumerate(zip(holdout_rows, predictions, strict=True)):
        execution_date = row.as_of + timedelta(days=1)
        signals.append(
            ForecastSignal(
                signal_id=SignalId.new(),
                instrument_id=instrument_id,
                model_version_id=result.model_version_id,
                as_of=row.as_of,
                generated_at=UtcInstant(
                    datetime.combine(row.as_of, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=22)
                ),
                expected_return=Decimal(format(float(prediction), ".15g")),
            )
        )
        open_price = Decimal(100 + index)
        close_price = open_price + Decimal("1")
        bars.append(
            BacktestPriceBar(
                instrument_id=instrument_id,
                session_date=execution_date,
                opens_at=UtcInstant(
                    datetime.combine(execution_date, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=14, minutes=30)
                ),
                closes_at=UtcInstant(
                    datetime.combine(execution_date, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=21)
                ),
                open_price=Price(open_price, currency),
                high_price=Price(close_price + Decimal("1"), currency),
                low_price=Price(open_price - Decimal("1"), currency),
                close_price=Price(close_price, currency),
                volume=Quantity("100000"),
                source_fingerprint=f"{index + 1:064x}",
            )
        )

    backtest = BacktestEngine(TopKLongOnlyPolicy(), BpsExecutionCostModel()).run(
        tuple(bars),
        tuple(signals),
        BacktestConfig(
            name="reference-paper-evaluation",
            initial_cash=Money("100000", currency),
            costs=TransactionCostSettings(
                commission_bps="1",
                slippage_bps="2",
                half_spread_bps="1",
                fixed_commission="0.50",
                maximum_volume_participation="0.05",
            ),
            risk_limits=PortfolioRiskLimits(
                maximum_position_weight="0.5",
                maximum_gross_exposure="0.5",
                maximum_rebalance_turnover="1",
                maximum_drawdown="0.25",
                top_k=1,
            ),
        ),
    )

    assert result.model_card.holdout_score == result.holdout_report.metric("mae").value
    assert result.artifact.payload_sha256
    assert predictions.shape == (4,)
    assert backtest.metric("trade_count").value >= 1
    assert backtest.metric("total_transaction_cost").value > 0
    assert len(backtest.fingerprint) == 64
