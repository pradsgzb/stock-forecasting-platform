from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_predictor.domain.backtesting.models import (
    BacktestConfig,
    BacktestPriceBar,
    EquityPoint,
    PortfolioRiskLimits,
    TransactionCostSettings,
)
from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import Quantity


def bar(currency=Currency("USD")):
    return BacktestPriceBar(
        InstrumentId.new(),
        date(2025, 1, 2),
        UtcInstant(datetime(2025, 1, 2, 14, 30, tzinfo=UTC)),
        UtcInstant(datetime(2025, 1, 2, 21, tzinfo=UTC)),
        Price("100", currency),
        Price("105", currency),
        Price("95", currency),
        Price("102", currency),
        Quantity("10000"),
        "a" * 64,
    )


def test_cost_risk_and_config_models_validate_conservative_defaults() -> None:
    costs = TransactionCostSettings(
        commission_bps="1",
        slippage_bps="2",
        half_spread_bps="3",
        fixed_commission="1",
        maximum_volume_participation="0.1",
    )
    risk = PortfolioRiskLimits(
        maximum_position_weight="0.2",
        maximum_gross_exposure="0.8",
        maximum_rebalance_turnover="0.5",
        maximum_drawdown="0.2",
        top_k=5,
    )
    config = BacktestConfig("paper", Money("100000", Currency("USD")), costs, risk)
    assert costs.maximum_volume_participation == Decimal("0.1")
    assert risk.top_k == 5
    assert config.price_mode.value == "split_adjusted"
    assert len(config.fingerprint) == 64
    assert replace(config, name=" paper ").fingerprint == config.fingerprint

    with pytest.raises(DomainValidationError, match="cannot be negative"):
        TransactionCostSettings(commission_bps="-1")
    with pytest.raises(DomainValidationError, match=r"within \(0, 1\]"):
        TransactionCostSettings(maximum_volume_participation="0")
    with pytest.raises(DomainValidationError, match="Position weight"):
        PortfolioRiskLimits(maximum_position_weight="0")
    with pytest.raises(DomainValidationError, match="Maximum drawdown"):
        PortfolioRiskLimits(maximum_drawdown="1")
    with pytest.raises(DomainValidationError, match="positive initial cash"):
        BacktestConfig("", Money(0, Currency("USD")), costs, risk)


def test_backtest_bar_and_equity_point_enforce_market_invariants() -> None:
    valid = bar()
    assert valid.currency == Currency("USD")
    with pytest.raises(DomainValidationError, match="SHA-256"):
        replace(valid, source_fingerprint="bad")
    with pytest.raises(DomainValidationError, match="close must be after"):
        replace(valid, closes_at=valid.opens_at)
    with pytest.raises(DomainValidationError, match="low cannot exceed"):
        replace(valid, low_price=Price("106", Currency("USD")))

    point = EquityPoint(
        date(2025, 1, 2),
        Money("100", Currency("USD")),
        Money("50", Currency("USD")),
        Money("150", Currency("USD")),
        Decimal("0.1"),
    )
    assert point.equity.amount == Decimal("150")
    with pytest.raises(DomainValidationError, match=r"within \[0, 1\]"):
        replace(point, drawdown=Decimal("1.1"))
