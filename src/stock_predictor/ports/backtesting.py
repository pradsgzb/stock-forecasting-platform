"""Ports for portfolio construction and simulated execution policies."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Protocol, runtime_checkable

from stock_predictor.domain.backtesting.models import (
    BacktestPriceBar,
    ForecastSignal,
    OrderSide,
    PortfolioRiskLimits,
    TransactionCostSettings,
)
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.money import Money, Price
from stock_predictor.domain.common.values import Quantity


@runtime_checkable
class PortfolioConstructionPolicy(Protocol):
    def target_weights(
        self,
        signals: tuple[ForecastSignal, ...],
        risk_limits: PortfolioRiskLimits,
    ) -> Mapping[InstrumentId, Decimal]:
        ...


@runtime_checkable
class ExecutionCostModel(Protocol):
    def execute(
        self,
        side: OrderSide,
        requested_quantity: Quantity,
        bar: BacktestPriceBar,
        settings: TransactionCostSettings,
    ) -> tuple[Quantity, Price, Money]:
        ...
