from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stock_predictor.application.backtesting.engine import BacktestEngine
from stock_predictor.application.backtesting.policies import (
    BpsExecutionCostModel,
    TopKLongOnlyPolicy,
)
from stock_predictor.domain.backtesting.models import (
    BacktestConfig,
    BacktestPriceBar,
    ForecastSignal,
    OrderSide,
    PortfolioRiskLimits,
    TransactionCostSettings,
)
from stock_predictor.domain.common.errors import BacktestError
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    ModelVersionId,
    SignalId,
)
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import Quantity

USD = Currency("USD")


def make_bar(instrument_id, session_date, open_price, close_price, volume="10000"):
    open_value = Decimal(str(open_price))
    close_value = Decimal(str(close_price))
    low = min(open_value, close_value) * Decimal("0.99")
    high = max(open_value, close_value) * Decimal("1.01")
    return BacktestPriceBar(
        instrument_id,
        session_date,
        UtcInstant(
            datetime.combine(session_date, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=14, minutes=30)
        ),
        UtcInstant(
            datetime.combine(session_date, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=21)
        ),
        Price(open_value, USD),
        Price(high, USD),
        Price(low, USD),
        Price(close_value, USD),
        Quantity(volume),
        f"{session_date.toordinal():064x}"[-64:],
    )


def signal(instrument_id, as_of, expected, hour=22):
    return ForecastSignal(
        SignalId.new(),
        instrument_id,
        ModelVersionId.new(),
        as_of,
        UtcInstant(
            datetime.combine(as_of, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=hour)
        ),
        expected,
    )


def config(*, benchmark_instrument_id=None, **risk_kwargs):
    return BacktestConfig(
        "paper",
        Money("100000", USD),
        TransactionCostSettings(
            commission_bps="1",
            slippage_bps="2",
            half_spread_bps="1",
            fixed_commission="0.50",
            maximum_volume_participation="0.1",
        ),
        PortfolioRiskLimits(
            maximum_position_weight="0.5",
            maximum_gross_exposure="1",
            maximum_rebalance_turnover="1",
            maximum_drawdown=risk_kwargs.get("maximum_drawdown", "0.5"),
            minimum_signal="0",
            top_k=2,
        ),
        benchmark_instrument_id=benchmark_instrument_id,
    )


def test_policy_and_execution_model_apply_limits_and_costs() -> None:
    first = InstrumentId.new()
    second = InstrumentId.new()
    third = InstrumentId.new()
    as_of = date(2025, 1, 2)
    weights = TopKLongOnlyPolicy().target_weights(
        (
            signal(first, as_of, "0.1"),
            signal(second, as_of, "0.2"),
            signal(third, as_of, "-0.1"),
        ),
        PortfolioRiskLimits(
            maximum_position_weight="0.4",
            maximum_gross_exposure="0.8",
            top_k=2,
        ),
    )
    assert weights == {second: Decimal("0.4"), first: Decimal("0.4")}

    market_bar = make_bar(first, date(2025, 1, 3), 100, 101, volume="100")
    quantity, price, commission = BpsExecutionCostModel().execute(
        OrderSide.BUY,
        Quantity("50"),
        market_bar,
        TransactionCostSettings(
            commission_bps="10",
            slippage_bps="5",
            half_spread_bps="5",
            fixed_commission="1",
            maximum_volume_participation="0.1",
        ),
    )
    assert quantity.value == Decimal("10")
    assert price.amount == Decimal("100.100")
    assert commission.amount == Decimal("2.001000")


def test_backtest_executes_only_after_signal_and_records_cost_aware_metrics() -> None:
    instrument_id = InstrumentId.new()
    dates = tuple(date(2025, 1, 2) + timedelta(days=index) for index in range(5))
    bars = tuple(
        make_bar(instrument_id, day, 100 + index, 101 + index)
        for index, day in enumerate(dates)
    )
    signals = (
        signal(instrument_id, dates[0], "0.10"),
        signal(instrument_id, dates[2], "-0.05"),
    )

    result = BacktestEngine(TopKLongOnlyPolicy(), BpsExecutionCostModel()).run(
        bars,
        signals,
        config(),
    )

    assert result.fills[0].session_date == dates[1]
    assert result.fills[0].side is OrderSide.BUY
    assert any(item.side is OrderSide.SELL for item in result.fills)
    assert result.metric("trade_count").value == len(result.fills)
    assert result.metric("total_transaction_cost").value > 0
    assert result.equity_curve[-1].equity.amount > 0
    assert len(result.fingerprint) == 64


def test_backtest_risk_halt_liquidates_on_following_session() -> None:
    instrument_id = InstrumentId.new()
    dates = tuple(date(2025, 2, 3) + timedelta(days=index) for index in range(4))
    bars = (
        make_bar(instrument_id, dates[0], 100, 100),
        make_bar(instrument_id, dates[1], 100, 100),
        make_bar(instrument_id, dates[2], 100, 50),
        make_bar(instrument_id, dates[3], 50, 50),
    )
    result = BacktestEngine(TopKLongOnlyPolicy(), BpsExecutionCostModel()).run(
        bars,
        (signal(instrument_id, dates[0], "0.2"),),
        config(maximum_drawdown="0.1"),
    )
    assert result.risk_halt_triggered
    assert any(
        fill.session_date == dates[3] and fill.side is OrderSide.SELL
        for fill in result.fills
    )
    assert result.final_positions == ()


def test_backtest_rejects_invalid_data_and_never_executes_future_signal() -> None:
    instrument_id = InstrumentId.new()
    day = date(2025, 1, 2)
    market_bar = make_bar(instrument_id, day, 100, 100)
    engine = BacktestEngine(TopKLongOnlyPolicy(), BpsExecutionCostModel())
    with pytest.raises(BacktestError, match="at least one"):
        engine.run((), (), config())
    with pytest.raises(BacktestError, match="unique"):
        engine.run((market_bar, market_bar), (), config())

    future_signal = signal(instrument_id, day + timedelta(days=1), "0.2")
    result = engine.run((market_bar,), (future_signal,), config())
    assert result.fills == ()


def test_backtest_is_content_deterministic_and_reports_benchmark_metrics() -> None:
    instrument_id = InstrumentId.new()
    benchmark_id = InstrumentId.new()
    dates = tuple(date(2025, 3, 3) + timedelta(days=index) for index in range(4))
    bars = tuple(
        bar
        for index, day in enumerate(dates)
        for bar in (
            make_bar(instrument_id, day, 100 + index, 101 + index),
            make_bar(benchmark_id, day, 200 + index, 201 + index),
        )
    )
    run_config = config(benchmark_instrument_id=benchmark_id)
    engine = BacktestEngine(TopKLongOnlyPolicy(), BpsExecutionCostModel())
    signals = (signal(instrument_id, dates[0], "0.1"),)
    first = engine.run(bars, signals, run_config)
    second = engine.run(bars, signals, run_config)

    assert first.run_id != second.run_id
    assert first.fingerprint == second.fingerprint
    assert first.config.fingerprint == run_config.fingerprint
    assert first.metric("benchmark_total_return").value > 0
    assert first.metric("tracking_error").value >= 0
    assert first.metric("total_transaction_cost").value >= first.metric(
        "total_commission"
    ).value


def test_backtest_requires_complete_benchmark_series() -> None:
    instrument_id = InstrumentId.new()
    benchmark_id = InstrumentId.new()
    first_day = date(2025, 4, 1)
    second_day = first_day + timedelta(days=1)
    bars = (
        make_bar(instrument_id, first_day, 100, 101),
        make_bar(benchmark_id, first_day, 200, 201),
        make_bar(instrument_id, second_day, 101, 102),
    )
    with pytest.raises(BacktestError, match="every backtest session"):
        BacktestEngine(TopKLongOnlyPolicy(), BpsExecutionCostModel()).run(
            bars,
            (),
            config(benchmark_instrument_id=benchmark_id),
        )
