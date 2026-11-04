"""Reference long-only portfolio construction and explicit execution-cost policies."""

from __future__ import annotations

from decimal import Decimal

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


class TopKLongOnlyPolicy:
    """Equal-weights the strongest positive signals within declared exposure limits."""

    def target_weights(
        self,
        signals: tuple[ForecastSignal, ...],
        risk_limits: PortfolioRiskLimits,
    ) -> dict[InstrumentId, Decimal]:
        eligible = tuple(
            sorted(
                (
                    item
                    for item in signals
                    if item.expected_return > risk_limits.minimum_signal
                ),
                key=lambda item: (-item.expected_return, str(item.instrument_id)),
            )[: risk_limits.top_k]
        )
        if not eligible:
            return {}
        equal_weight = risk_limits.maximum_gross_exposure / Decimal(len(eligible))
        position_weight = min(equal_weight, risk_limits.maximum_position_weight)
        return {item.instrument_id: position_weight for item in eligible}


class BpsExecutionCostModel:
    """Volume-capped next-open execution with spread, slippage, and commission."""

    _BASIS_POINTS = Decimal(10_000)

    def execute(
        self,
        side: OrderSide,
        requested_quantity: Quantity,
        bar: BacktestPriceBar,
        settings: TransactionCostSettings,
    ) -> tuple[Quantity, Price, Money]:
        maximum_quantity = bar.volume.value * settings.maximum_volume_participation
        filled_quantity = min(requested_quantity.value, maximum_quantity)
        if filled_quantity <= 0:
            return Quantity(0), bar.open_price, Money.zero(bar.currency)
        direction = Decimal(1) if side is OrderSide.BUY else Decimal(-1)
        price_multiplier = Decimal(1) + direction * (
            settings.slippage_bps + settings.half_spread_bps
        ) / self._BASIS_POINTS
        execution_price = Price(
            bar.open_price.amount * price_multiplier,
            bar.currency,
        )
        gross_notional = execution_price.amount * filled_quantity
        commission = settings.fixed_commission + gross_notional * (
            settings.commission_bps / self._BASIS_POINTS
        )
        return (
            Quantity(filled_quantity),
            execution_price,
            Money(commission, bar.currency),
        )
