"""Event-driven paper backtester with strict signal timing, costs, and risk limits."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping

import numpy as np
from numpy.typing import NDArray

from stock_predictor.domain.backtesting.models import (
    BacktestConfig,
    BacktestMetric,
    BacktestPriceBar,
    BacktestResult,
    EquityPoint,
    ForecastSignal,
    OrderSide,
    PositionSnapshot,
    SimulatedFill,
)
from stock_predictor.domain.common.errors import BacktestError
from stock_predictor.domain.common.identifiers import (
    BacktestRunId,
    FillId,
    InstrumentId,
    OrderId,
)
from stock_predictor.domain.common.money import Money, Price
from stock_predictor.domain.common.values import Quantity
from stock_predictor.ports.backtesting import (
    ExecutionCostModel,
    PortfolioConstructionPolicy,
)


@dataclass(slots=True)
class _PortfolioState:
    cash: Decimal
    positions: dict[InstrumentId, Decimal]
    last_prices: dict[InstrumentId, Decimal]
    peak_equity: Decimal
    risk_halted: bool = False


class BacktestEngine:
    """Simulates next-session-open fills; it has no broker or live-order capability."""

    __slots__ = ("_execution", "_portfolio_policy")

    def __init__(
        self,
        portfolio_policy: PortfolioConstructionPolicy,
        execution: ExecutionCostModel,
    ) -> None:
        self._portfolio_policy = portfolio_policy
        self._execution = execution

    def run(
        self,
        bars: tuple[BacktestPriceBar, ...],
        signals: tuple[ForecastSignal, ...],
        config: BacktestConfig,
    ) -> BacktestResult:
        if not bars:
            raise BacktestError("Backtest requires at least one market bar")
        if any(item.currency != config.initial_cash.currency for item in bars):
            raise BacktestError("Backtest currently requires one portfolio currency")
        bar_keys = tuple((item.instrument_id, item.session_date) for item in bars)
        if len(set(bar_keys)) != len(bar_keys):
            raise BacktestError("Backtest bars must be unique by instrument and session")
        bars_by_date: dict[date, dict[InstrumentId, BacktestPriceBar]] = defaultdict(dict)
        for bar in bars:
            bars_by_date[bar.session_date][bar.instrument_id] = bar
        dates = tuple(sorted(bars_by_date))
        signal_keys = tuple(item.signal_id for item in signals)
        if len(set(signal_keys)) != len(signal_keys):
            raise BacktestError("Forecast signal IDs must be unique")
        ordered_signals = tuple(
            sorted(signals, key=lambda item: (item.as_of, item.generated_at, str(item.signal_id)))
        )
        state = _PortfolioState(
            cash=config.initial_cash.amount,
            positions={},
            last_prices={},
            peak_equity=config.initial_cash.amount,
        )
        latest_signals: dict[InstrumentId, ForecastSignal] = {}
        fills: list[SimulatedFill] = []
        equity_curve: list[EquityPoint] = []
        for session_date in dates:
            session_bars = bars_by_date[session_date]
            self._activate_signals(
                ordered_signals,
                session_date,
                session_bars,
                latest_signals,
            )
            opening_equity = self._mark_to_market(state, session_bars, use_open=True)
            if opening_equity <= 0:
                raise BacktestError("Portfolio equity became non-positive before execution")
            target_weights = (
                {}
                if state.risk_halted
                else self._portfolio_policy.target_weights(
                    tuple(latest_signals.values()),
                    config.risk_limits,
                )
            )
            desired = self._desired_notional_deltas(
                state,
                session_bars,
                target_weights,
                opening_equity,
                config,
            )
            for instrument_id, delta in sorted(
                desired.items(), key=lambda item: (item[1] >= 0, str(item[0]))
            ):
                bar = session_bars.get(instrument_id)
                if bar is None or delta == 0:
                    continue
                signal = latest_signals.get(instrument_id)
                fill = self._execute_delta(
                    state,
                    bar,
                    delta,
                    signal,
                    config,
                )
                if fill is not None:
                    fills.append(fill)
            for instrument_id, bar in session_bars.items():
                state.last_prices[instrument_id] = bar.close_price.amount
            closing_equity = self._mark_to_market(state, session_bars, use_open=False)
            if closing_equity <= 0:
                raise BacktestError("Portfolio equity became non-positive")
            state.peak_equity = max(state.peak_equity, closing_equity)
            drawdown = Decimal(1) - (closing_equity / state.peak_equity)
            if drawdown >= config.risk_limits.maximum_drawdown:
                state.risk_halted = True
            gross = sum(
                (
                    abs(quantity)
                    * state.last_prices[instrument_id]
                    for instrument_id, quantity in state.positions.items()
                ),
                start=Decimal(0),
            )
            equity_curve.append(
                EquityPoint(
                    session_date=session_date,
                    cash=Money(state.cash, config.initial_cash.currency),
                    gross_exposure=Money(gross, config.initial_cash.currency),
                    equity=Money(closing_equity, config.initial_cash.currency),
                    drawdown=drawdown,
                )
            )
        final_date = dates[-1]
        final_positions = self._final_positions(
            state,
            bars_by_date[final_date],
            equity_curve[-1].equity.amount,
            final_date,
            config,
        )
        benchmark_returns = self._benchmark_returns(
            dates,
            bars_by_date,
            config,
        )
        return BacktestResult(
            run_id=BacktestRunId.new(),
            config=config,
            started_at=min(item.opens_at for item in bars),
            completed_at=max(item.closes_at for item in bars),
            equity_curve=tuple(equity_curve),
            fills=tuple(fills),
            final_positions=final_positions,
            metrics=self._metrics(
                tuple(equity_curve),
                tuple(fills),
                config,
                benchmark_returns,
            ),
            risk_halt_triggered=state.risk_halted,
        )

    @staticmethod
    def _activate_signals(
        signals: tuple[ForecastSignal, ...],
        session_date: date,
        session_bars: dict[InstrumentId, BacktestPriceBar],
        latest: dict[InstrumentId, ForecastSignal],
    ) -> None:
        for signal in signals:
            if signal.as_of >= session_date:
                continue
            bar = session_bars.get(signal.instrument_id)
            if bar is None or signal.generated_at > bar.opens_at:
                continue
            previous = latest.get(signal.instrument_id)
            if previous is None or (signal.as_of, signal.generated_at) > (
                previous.as_of,
                previous.generated_at,
            ):
                latest[signal.instrument_id] = signal

    @staticmethod
    def _mark_to_market(
        state: _PortfolioState,
        session_bars: dict[InstrumentId, BacktestPriceBar],
        *,
        use_open: bool,
    ) -> Decimal:
        market_value = Decimal(0)
        for instrument_id, quantity in state.positions.items():
            bar = session_bars.get(instrument_id)
            if bar is not None:
                price = bar.open_price.amount if use_open else bar.close_price.amount
            else:
                try:
                    price = state.last_prices[instrument_id]
                except KeyError as exc:
                    raise BacktestError(
                        f"No valuation price for open position {instrument_id}"
                    ) from exc
            market_value += quantity * price
        return state.cash + market_value

    @staticmethod
    def _desired_notional_deltas(
        state: _PortfolioState,
        session_bars: dict[InstrumentId, BacktestPriceBar],
        target_weights: Mapping[InstrumentId, Decimal],
        opening_equity: Decimal,
        config: BacktestConfig,
    ) -> dict[InstrumentId, Decimal]:
        normalized_weights = dict(target_weights)
        if any(value < 0 for value in normalized_weights.values()):
            raise BacktestError("Long-only policy returned a negative target weight")
        if sum(normalized_weights.values(), start=Decimal(0)) > (
            config.risk_limits.maximum_gross_exposure + Decimal("1e-18")
        ):
            raise BacktestError("Portfolio policy exceeded maximum gross exposure")
        instruments = set(state.positions) | set(normalized_weights)
        deltas: dict[InstrumentId, Decimal] = {}
        for instrument_id in instruments:
            bar = session_bars.get(instrument_id)
            if bar is None:
                continue
            current = state.positions.get(instrument_id, Decimal(0)) * bar.open_price.amount
            target = normalized_weights.get(instrument_id, Decimal(0)) * opening_equity
            deltas[instrument_id] = target - current
        turnover = sum((abs(value) for value in deltas.values()), start=Decimal(0))
        maximum = config.risk_limits.maximum_rebalance_turnover * opening_equity
        if turnover > maximum and turnover > 0:
            scale = maximum / turnover
            deltas = {key: value * scale for key, value in deltas.items()}
        return deltas

    def _execute_delta(
        self,
        state: _PortfolioState,
        bar: BacktestPriceBar,
        notional_delta: Decimal,
        signal: ForecastSignal | None,
        config: BacktestConfig,
    ) -> SimulatedFill | None:
        side = OrderSide.BUY if notional_delta > 0 else OrderSide.SELL
        requested = abs(notional_delta) / bar.open_price.amount
        if side is OrderSide.SELL:
            requested = min(requested, state.positions.get(bar.instrument_id, Decimal(0)))
        if requested <= 0:
            return None
        order_id = OrderId.new()
        quantity, price, commission = self._execution.execute(
            side,
            Quantity(requested),
            bar,
            config.costs,
        )
        if quantity.value <= 0:
            return None
        gross = quantity.value * price.amount
        if side is OrderSide.BUY and gross + commission.amount > state.cash:
            affordable_ratio = state.cash / (gross + commission.amount)
            if affordable_ratio <= 0:
                return None
            quantity, price, commission = self._execution.execute(
                side,
                Quantity(quantity.value * affordable_ratio),
                bar,
                config.costs,
            )
            gross = quantity.value * price.amount
            if quantity.value <= 0 or gross + commission.amount > state.cash:
                return None
        current = state.positions.get(bar.instrument_id, Decimal(0))
        if side is OrderSide.BUY:
            state.cash -= gross + commission.amount
            state.positions[bar.instrument_id] = current + quantity.value
        else:
            state.cash += gross - commission.amount
            remaining = current - quantity.value
            if remaining < Decimal("1e-18"):
                state.positions.pop(bar.instrument_id, None)
            else:
                state.positions[bar.instrument_id] = remaining
        return SimulatedFill(
            fill_id=FillId.new(),
            order_id=order_id,
            instrument_id=bar.instrument_id,
            session_date=bar.session_date,
            side=side,
            quantity=quantity,
            reference_price=bar.open_price,
            execution_price=price,
            commission=commission,
            executed_at=bar.opens_at,
            signal_id=signal.signal_id if signal is not None else None,
        )

    @staticmethod
    def _benchmark_returns(
        dates: tuple[date, ...],
        bars_by_date: dict[date, dict[InstrumentId, BacktestPriceBar]],
        config: BacktestConfig,
    ) -> NDArray[np.float64] | None:
        benchmark_id = config.benchmark_instrument_id
        if benchmark_id is None:
            return None
        benchmark_bars: list[BacktestPriceBar] = []
        for session_date in dates:
            bar = bars_by_date[session_date].get(benchmark_id)
            if bar is None:
                raise BacktestError(
                    "Configured benchmark requires one bar for every backtest session"
                )
            benchmark_bars.append(bar)
        values: list[float] = []
        previous = benchmark_bars[0].open_price.amount
        for bar in benchmark_bars:
            values.append(float(bar.close_price.amount / previous - Decimal(1)))
            previous = bar.close_price.amount
        return np.asarray(values, dtype=np.float64)

    @staticmethod
    def _final_positions(
        state: _PortfolioState,
        final_bars: dict[InstrumentId, BacktestPriceBar],
        final_equity: Decimal,
        final_date: date,
        config: BacktestConfig,
    ) -> tuple[PositionSnapshot, ...]:
        result: list[PositionSnapshot] = []
        for instrument_id, quantity in sorted(
            state.positions.items(), key=lambda item: str(item[0])
        ):
            bar = final_bars.get(instrument_id)
            price_amount = (
                bar.close_price.amount
                if bar is not None
                else state.last_prices[instrument_id]
            )
            market_value = quantity * price_amount
            price = Price(price_amount, config.initial_cash.currency)
            result.append(
                PositionSnapshot(
                    instrument_id=instrument_id,
                    session_date=final_date,
                    quantity=quantity,
                    close_price=price,
                    market_value=Money(market_value, config.initial_cash.currency),
                    portfolio_weight=market_value / final_equity,
                )
            )
        return tuple(result)

    @staticmethod
    def _metrics(
        equity_curve: tuple[EquityPoint, ...],
        fills: tuple[SimulatedFill, ...],
        config: BacktestConfig,
        benchmark_returns: NDArray[np.float64] | None,
    ) -> tuple[BacktestMetric, ...]:
        equities = np.asarray(
            [float(item.equity.amount) for item in equity_curve],
            dtype=np.float64,
        )
        initial = float(config.initial_cash.amount)
        total_return = equities[-1] / initial - 1.0
        first_period_return = np.asarray([equities[0] / initial - 1.0])
        subsequent_returns = (
            equities[1:] / equities[:-1] - 1.0
            if equities.size > 1
            else np.asarray([], dtype=np.float64)
        )
        returns = np.concatenate((first_period_return, subsequent_returns))
        periods = int(returns.size)
        annualized_return = (
            (1.0 + total_return) ** (config.annualization_sessions / periods) - 1.0
            if total_return > -1.0
            else -1.0
        )
        volatility = (
            float(np.std(returns, ddof=1)) * math.sqrt(config.annualization_sessions)
            if returns.size > 1
            else 0.0
        )
        mean_return = float(np.mean(returns)) if returns.size else 0.0
        standard_deviation = float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0
        sharpe = (
            mean_return / standard_deviation * math.sqrt(config.annualization_sessions)
            if standard_deviation > 0
            else 0.0
        )
        downside = returns[returns < 0]
        downside_deviation = (
            float(np.std(downside, ddof=1)) if downside.size > 1 else 0.0
        )
        sortino = (
            mean_return / downside_deviation * math.sqrt(config.annualization_sessions)
            if downside_deviation > 0
            else 0.0
        )
        gains = float(np.sum(returns[returns > 0])) if returns.size else 0.0
        losses = abs(float(np.sum(returns[returns < 0]))) if returns.size else 0.0
        profit_factor = gains / losses if losses > 0 else 0.0
        traded_notional = sum(
            (item.gross_notional.amount for item in fills), start=Decimal(0)
        )
        average_equity = Decimal(str(float(np.mean(equities))))
        turnover = traded_notional / average_equity if average_equity > 0 else Decimal(0)
        total_commission = sum(
            (item.commission.amount for item in fills), start=Decimal(0)
        )
        total_costs = sum(
            (item.implementation_shortfall.amount for item in fills),
            start=Decimal(0),
        )
        metrics: list[BacktestMetric] = [
            BacktestMetric("total_return", BacktestEngine._metric_decimal(total_return)),
            BacktestMetric(
                "annualized_return", BacktestEngine._metric_decimal(annualized_return)
            ),
            BacktestMetric(
                "annualized_volatility", BacktestEngine._metric_decimal(volatility)
            ),
            BacktestMetric("sharpe_ratio", BacktestEngine._metric_decimal(sharpe)),
            BacktestMetric("sortino_ratio", BacktestEngine._metric_decimal(sortino)),
            BacktestMetric(
                "maximum_drawdown", max(item.drawdown for item in equity_curve)
            ),
            BacktestMetric(
                "hit_rate",
                BacktestEngine._metric_decimal(float(np.mean(returns > 0)))
                if returns.size
                else Decimal(0),
            ),
            BacktestMetric("profit_factor", BacktestEngine._metric_decimal(profit_factor)),
            BacktestMetric("turnover", turnover),
            BacktestMetric("total_transaction_cost", total_costs),
            BacktestMetric("total_commission", total_commission),
            BacktestMetric("trade_count", len(fills)),
            BacktestMetric("ending_equity", BacktestEngine._metric_decimal(equities[-1])),
        ]
        if benchmark_returns is not None:
            if benchmark_returns.shape != equities.shape:
                raise BacktestError("Benchmark and portfolio return series are misaligned")
            benchmark_total = float(np.prod(1.0 + benchmark_returns) - 1.0)
            active_returns = returns - benchmark_returns
            tracking_error = (
                float(np.std(active_returns, ddof=1))
                * math.sqrt(config.annualization_sessions)
                if active_returns.size > 1
                else 0.0
            )
            metrics.extend(
                (
                    BacktestMetric(
                        "benchmark_total_return",
                        BacktestEngine._metric_decimal(benchmark_total),
                    ),
                    BacktestMetric(
                        "active_total_return",
                        BacktestEngine._metric_decimal(total_return - benchmark_total),
                    ),
                    BacktestMetric(
                        "tracking_error",
                        BacktestEngine._metric_decimal(tracking_error),
                    ),
                )
            )
        return tuple(metrics)

    @staticmethod
    def _metric_decimal(value: float | np.float64) -> Decimal:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise BacktestError("Backtest metric is not finite")
        return Decimal(format(numeric, ".15g"))
