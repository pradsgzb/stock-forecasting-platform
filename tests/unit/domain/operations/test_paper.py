from datetime import timedelta
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError, PaperTradingError
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    PaperAccountId,
    PaperFillId,
    PaperOrderId,
)
from stock_predictor.domain.common.money import Currency, Money, Price
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.operations.paper import (
    PaperAccount,
    PaperFill,
    PaperOrderSide,
    PaperPosition,
    PaperTradeRequest,
    execution_price,
)


def _fill(account, instrument_id, fixed_instant, side, quantity, price="100"):
    execution = Price(price, account.base_currency)
    return PaperFill(
        PaperFillId.new(),
        PaperOrderId.new(),
        account.account_id,
        instrument_id,
        side,
        Quantity(quantity),
        Price(price, account.base_currency),
        execution,
        Money(execution.amount * Decimal(quantity), account.base_currency),
        Money("1", account.base_currency),
        fixed_instant,
    )


def test_account_buy_and_sell_accounting(fixed_instant) -> None:
    instrument_id = InstrumentId.new()
    account = PaperAccount.open(
        account_id=PaperAccountId.new(),
        owner_subject="operator-1",
        name="Research Account",
        initial_cash="1000",
        currency=Currency("USD"),
        opened_at=fixed_instant,
    )
    bought = account.apply_fill(
        _fill(account, instrument_id, fixed_instant, PaperOrderSide.BUY, "2")
    )
    sold = bought.apply_fill(
        _fill(
            bought,
            instrument_id,
            fixed_instant.plus(timedelta(seconds=1)),
            PaperOrderSide.SELL,
            "1",
            "110",
        )
    )

    assert bought.cash.amount == Decimal("799")
    assert bought.position(instrument_id).quantity.value == Decimal("2")
    assert sold.cash.amount == Decimal("908")
    assert sold.realized_pnl.amount == Decimal("9")
    assert sold.position(instrument_id).quantity.value == Decimal("1")


def test_account_disallows_short_and_insufficient_cash(fixed_instant) -> None:
    account = PaperAccount.open(
        account_id=PaperAccountId.new(),
        owner_subject="operator-1",
        name="Research Account",
        initial_cash="100",
        currency=Currency("USD"),
        opened_at=fixed_instant,
    )
    instrument_id = InstrumentId.new()
    with pytest.raises(PaperTradingError, match="Insufficient"):
        account.apply_fill(
            _fill(account, instrument_id, fixed_instant, PaperOrderSide.BUY, "2")
        )
    with pytest.raises(PaperTradingError, match="Short selling"):
        account.apply_fill(
            _fill(account, instrument_id, fixed_instant, PaperOrderSide.SELL, "1")
        )


def test_execution_price_applies_cost_direction() -> None:
    reference = Price("100", Currency("USD"))

    buy = execution_price(reference, PaperOrderSide.BUY, spread_bps="10", slippage_bps="5")
    sell = execution_price(reference, PaperOrderSide.SELL, spread_bps="10", slippage_bps="5")

    assert buy.amount == Decimal("100.100")
    assert sell.amount == Decimal("99.900")


def test_paper_request_hash_is_stable(fixed_instant) -> None:
    request = PaperTradeRequest(
        PaperAccountId.new(),
        InstrumentId.new(),
        PaperOrderSide.BUY,
        Quantity("1"),
        Price("100", Currency("USD")),
        fixed_instant,
        "paper-order-key-1",
    )

    assert request.request_hash == request.request_hash
    assert len(request.request_hash) == 64


def test_position_and_fill_validate_values(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="positive"):
        PaperPosition(InstrumentId.new(), Quantity("0"), Price("1", Currency("USD")))
    account_id = PaperAccountId.new()
    with pytest.raises(DomainValidationError, match="notional"):
        PaperFill(
            PaperFillId.new(),
            PaperOrderId.new(),
            account_id,
            InstrumentId.new(),
            PaperOrderSide.BUY,
            Quantity("1"),
            Price("10", Currency("USD")),
            Price("10", Currency("USD")),
            Money("9", Currency("USD")),
            Money("0", Currency("USD")),
            fixed_instant,
        )
