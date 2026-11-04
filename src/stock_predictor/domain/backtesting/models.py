"""Immutable paper-trading and research-backtest domain models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    BacktestRunId,
    FillId,
    InstrumentId,
    ModelVersionId,
    OrderId,
    SignalId,
)
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, Probability, Quantity, to_decimal


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class BacktestPriceMode(StrEnum):
    """Explicit research-price convention used by the simulator."""

    SPLIT_ADJUSTED = "split_adjusted"


@dataclass(frozen=True, slots=True)
class BacktestPriceBar:
    instrument_id: InstrumentId
    session_date: date
    opens_at: UtcInstant
    closes_at: UtcInstant
    open_price: Price
    high_price: Price
    low_price: Price
    close_price: Price
    volume: Quantity
    source_fingerprint: str

    def __post_init__(self) -> None:
        if self.closes_at <= self.opens_at:
            raise DomainValidationError("Backtest bar close must be after open")
        currencies = {
            self.open_price.currency,
            self.high_price.currency,
            self.low_price.currency,
            self.close_price.currency,
        }
        if len(currencies) != 1:
            raise DomainValidationError("Backtest OHLC values must share a currency")
        if self.low_price > self.high_price:
            raise DomainValidationError("Backtest low cannot exceed high")
        if not self.low_price <= self.open_price <= self.high_price:
            raise DomainValidationError("Backtest open must fall within low/high")
        if not self.low_price <= self.close_price <= self.high_price:
            raise DomainValidationError("Backtest close must fall within low/high")
        fingerprint = self.source_fingerprint.strip().lower()
        if len(fingerprint) != 64 or any(item not in "0123456789abcdef" for item in fingerprint):
            raise DomainValidationError("Backtest source fingerprint must be SHA-256")
        object.__setattr__(self, "source_fingerprint", fingerprint)

    @property
    def currency(self) -> Currency:
        return self.close_price.currency


@dataclass(frozen=True, slots=True)
class ForecastSignal:
    """Immutable forecast available only after its generation timestamp."""

    signal_id: SignalId
    instrument_id: InstrumentId
    model_version_id: ModelVersionId
    as_of: date
    generated_at: UtcInstant
    expected_return: Decimal
    confidence: Probability | None = None

    def __init__(
        self,
        signal_id: SignalId,
        instrument_id: InstrumentId,
        model_version_id: ModelVersionId,
        as_of: date,
        generated_at: UtcInstant,
        expected_return: DecimalInput,
        confidence: Probability | None = None,
    ) -> None:
        object.__setattr__(self, "signal_id", signal_id)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "model_version_id", model_version_id)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "generated_at", generated_at)
        object.__setattr__(
            self,
            "expected_return",
            to_decimal(expected_return, field_name="expected return"),
        )
        object.__setattr__(self, "confidence", confidence)


@dataclass(frozen=True, slots=True)
class TransactionCostSettings:
    commission_bps: Decimal = Decimal(0)
    slippage_bps: Decimal = Decimal(0)
    half_spread_bps: Decimal = Decimal(0)
    fixed_commission: Decimal = Decimal(0)
    maximum_volume_participation: Decimal = Decimal("0.05")

    def __init__(
        self,
        *,
        commission_bps: DecimalInput = Decimal(0),
        slippage_bps: DecimalInput = Decimal(0),
        half_spread_bps: DecimalInput = Decimal(0),
        fixed_commission: DecimalInput = Decimal(0),
        maximum_volume_participation: DecimalInput = Decimal("0.05"),
    ) -> None:
        commission = to_decimal(commission_bps, field_name="commission bps")
        slippage = to_decimal(slippage_bps, field_name="slippage bps")
        spread = to_decimal(half_spread_bps, field_name="half spread bps")
        fixed = to_decimal(fixed_commission, field_name="fixed commission")
        participation = to_decimal(
            maximum_volume_participation,
            field_name="maximum volume participation",
        )
        if any(value < 0 for value in (commission, slippage, spread, fixed)):
            raise DomainValidationError("Transaction costs cannot be negative")
        if not Decimal(0) < participation <= Decimal(1):
            raise DomainValidationError("Volume participation must be within (0, 1]")
        object.__setattr__(self, "commission_bps", commission)
        object.__setattr__(self, "slippage_bps", slippage)
        object.__setattr__(self, "half_spread_bps", spread)
        object.__setattr__(self, "fixed_commission", fixed)
        object.__setattr__(self, "maximum_volume_participation", participation)


@dataclass(frozen=True, slots=True)
class PortfolioRiskLimits:
    maximum_position_weight: Decimal = Decimal("0.20")
    maximum_gross_exposure: Decimal = Decimal("1.00")
    maximum_rebalance_turnover: Decimal = Decimal("1.00")
    maximum_drawdown: Decimal = Decimal("0.25")
    minimum_signal: Decimal = Decimal(0)
    top_k: int = 10

    def __init__(
        self,
        *,
        maximum_position_weight: DecimalInput = Decimal("0.20"),
        maximum_gross_exposure: DecimalInput = Decimal("1.00"),
        maximum_rebalance_turnover: DecimalInput = Decimal("1.00"),
        maximum_drawdown: DecimalInput = Decimal("0.25"),
        minimum_signal: DecimalInput = Decimal(0),
        top_k: int = 10,
    ) -> None:
        position = to_decimal(maximum_position_weight, field_name="maximum position weight")
        gross = to_decimal(maximum_gross_exposure, field_name="maximum gross exposure")
        turnover = to_decimal(
            maximum_rebalance_turnover,
            field_name="maximum rebalance turnover",
        )
        drawdown = to_decimal(maximum_drawdown, field_name="maximum drawdown")
        signal = to_decimal(minimum_signal, field_name="minimum signal")
        if not Decimal(0) < position <= Decimal(1):
            raise DomainValidationError("Position weight must be within (0, 1]")
        if not Decimal(0) < gross <= Decimal(1):
            raise DomainValidationError("Long-only gross exposure must be within (0, 1]")
        if turnover <= 0:
            raise DomainValidationError("Maximum turnover must be positive")
        if not Decimal(0) < drawdown < Decimal(1):
            raise DomainValidationError("Maximum drawdown must be within (0, 1)")
        if top_k <= 0:
            raise DomainValidationError("Top-k count must be positive")
        object.__setattr__(self, "maximum_position_weight", position)
        object.__setattr__(self, "maximum_gross_exposure", gross)
        object.__setattr__(self, "maximum_rebalance_turnover", turnover)
        object.__setattr__(self, "maximum_drawdown", drawdown)
        object.__setattr__(self, "minimum_signal", signal)
        object.__setattr__(self, "top_k", top_k)


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    name: str
    initial_cash: Money
    costs: TransactionCostSettings
    risk_limits: PortfolioRiskLimits
    annualization_sessions: int = 252
    price_mode: BacktestPriceMode = BacktestPriceMode.SPLIT_ADJUSTED
    benchmark_instrument_id: InstrumentId | None = None

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name or self.initial_cash.amount <= 0:
            raise DomainValidationError("Backtest name and positive initial cash are required")
        if self.annualization_sessions <= 0:
            raise DomainValidationError("Annualization sessions must be positive")
        object.__setattr__(self, "name", normalized_name)

    @property
    def fingerprint(self) -> str:
        payload = {
            "name": self.name,
            "initial_cash": str(self.initial_cash.amount),
            "currency": str(self.initial_cash.currency),
            "costs": {
                "commission_bps": str(self.costs.commission_bps),
                "slippage_bps": str(self.costs.slippage_bps),
                "half_spread_bps": str(self.costs.half_spread_bps),
                "fixed_commission": str(self.costs.fixed_commission),
                "maximum_volume_participation": str(
                    self.costs.maximum_volume_participation
                ),
            },
            "risk_limits": {
                "maximum_position_weight": str(
                    self.risk_limits.maximum_position_weight
                ),
                "maximum_gross_exposure": str(
                    self.risk_limits.maximum_gross_exposure
                ),
                "maximum_rebalance_turnover": str(
                    self.risk_limits.maximum_rebalance_turnover
                ),
                "maximum_drawdown": str(self.risk_limits.maximum_drawdown),
                "minimum_signal": str(self.risk_limits.minimum_signal),
                "top_k": self.risk_limits.top_k,
            },
            "annualization_sessions": self.annualization_sessions,
            "price_mode": self.price_mode.value,
            "benchmark_instrument_id": (
                str(self.benchmark_instrument_id)
                if self.benchmark_instrument_id is not None
                else None
            ),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class SimulatedOrder:
    order_id: OrderId
    instrument_id: InstrumentId
    session_date: date
    side: OrderSide
    requested_quantity: Quantity
    signal_id: SignalId | None
    created_at: UtcInstant


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    fill_id: FillId
    order_id: OrderId
    instrument_id: InstrumentId
    session_date: date
    side: OrderSide
    quantity: Quantity
    reference_price: Price
    execution_price: Price
    commission: Money
    executed_at: UtcInstant
    signal_id: SignalId | None

    def __post_init__(self) -> None:
        if self.quantity.value <= 0:
            raise DomainValidationError("Fill quantity must be positive")
        if self.commission.amount < 0:
            raise DomainValidationError("Fill commission cannot be negative")
        currencies = {
            self.reference_price.currency,
            self.execution_price.currency,
            self.commission.currency,
        }
        if len(currencies) != 1:
            raise DomainValidationError(
                "Fill reference, execution, and commission currencies must match"
            )

    @property
    def gross_notional(self) -> Money:
        return Money(
            self.execution_price.amount * self.quantity.value,
            self.execution_price.currency,
        )

    @property
    def implementation_shortfall(self) -> Money:
        direction = Decimal(1) if self.side is OrderSide.BUY else Decimal(-1)
        price_cost = (
            direction
            * (self.execution_price.amount - self.reference_price.amount)
            * self.quantity.value
        )
        return Money(
            price_cost + self.commission.amount,
            self.execution_price.currency,
        )


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    instrument_id: InstrumentId
    session_date: date
    quantity: Decimal
    close_price: Price
    market_value: Money
    portfolio_weight: Decimal


@dataclass(frozen=True, slots=True)
class EquityPoint:
    session_date: date
    cash: Money
    gross_exposure: Money
    equity: Money
    drawdown: Decimal

    def __post_init__(self) -> None:
        currencies = {self.cash.currency, self.gross_exposure.currency, self.equity.currency}
        if len(currencies) != 1:
            raise DomainValidationError("Equity point values must share a currency")
        if self.gross_exposure.amount < 0 or self.equity.amount <= 0:
            raise DomainValidationError("Exposure cannot be negative and equity must be positive")
        if not Decimal(0) <= self.drawdown <= Decimal(1):
            raise DomainValidationError("Drawdown must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class BacktestMetric:
    name: str
    value: Decimal

    def __init__(self, name: str, value: DecimalInput) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise DomainValidationError("Backtest metric name is required")
        object.__setattr__(self, "name", normalized)
        object.__setattr__(self, "value", to_decimal(value, field_name=normalized))


@dataclass(frozen=True, slots=True)
class BacktestResult:
    run_id: BacktestRunId
    config: BacktestConfig
    started_at: UtcInstant
    completed_at: UtcInstant
    equity_curve: tuple[EquityPoint, ...]
    fills: tuple[SimulatedFill, ...]
    final_positions: tuple[PositionSnapshot, ...]
    metrics: tuple[BacktestMetric, ...]
    risk_halt_triggered: bool
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.completed_at < self.started_at:
            raise DomainValidationError("Backtest completion cannot precede start")
        if not self.equity_curve or not self.metrics:
            raise DomainValidationError("Backtest result requires equity and metrics")
        dates = tuple(item.session_date for item in self.equity_curve)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise DomainValidationError("Equity curve dates must be unique and ordered")
        names = tuple(item.name for item in self.metrics)
        if len(set(names)) != len(names):
            raise DomainValidationError("Backtest metric names must be unique")
        payload = {
            "config": self.config.fingerprint,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "equity": [
                (
                    item.session_date.isoformat(),
                    str(item.cash.amount),
                    str(item.gross_exposure.amount),
                    str(item.equity.amount),
                    str(item.drawdown),
                )
                for item in self.equity_curve
            ],
            "fills": [
                (
                    str(item.instrument_id),
                    item.session_date.isoformat(),
                    item.side.value,
                    str(item.quantity.value),
                    str(item.reference_price.amount),
                    str(item.execution_price.amount),
                    str(item.commission.amount),
                    item.executed_at.isoformat(),
                    str(item.signal_id) if item.signal_id is not None else None,
                )
                for item in self.fills
            ],
            "positions": [
                (
                    str(item.instrument_id),
                    item.session_date.isoformat(),
                    str(item.quantity),
                    str(item.close_price.amount),
                    str(item.market_value.amount),
                    str(item.portfolio_weight),
                )
                for item in self.final_positions
            ],
            "metrics": [(item.name, str(item.value)) for item in self.metrics],
            "risk_halt": self.risk_halt_triggered,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    def metric(self, name: str) -> BacktestMetric:
        normalized = name.strip().lower()
        for metric in self.metrics:
            if metric.name == normalized:
                return metric
        raise DomainValidationError(f"Backtest metric is not present: {normalized}")
