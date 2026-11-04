from datetime import timedelta
from decimal import Decimal

import pytest

from stock_predictor.adapters.observability.prometheus_telemetry import NoopTelemetry
from stock_predictor.application.paper_trading.service import (
    PaperTradingPolicy,
    PaperTradingService,
)
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import (
    AuthorizationError,
    IdempotencyConflictError,
    PaperTradingError,
)
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.money import Currency, Price
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.operations.paper import PaperOrderSide, PaperTradeRequest
from stock_predictor.domain.security.identity import Principal, PrincipalRole


def _service(store, instant, **policy) -> PaperTradingService:
    return PaperTradingService(
        store,
        FixedClock(instant),
        NoopTelemetry(),
        policy=PaperTradingPolicy(**policy),
    )


def _account(service, principal, *, key="account-key-001", cash="10000"):
    return service.open_account(
        principal=principal,
        name="Research Portfolio",
        initial_cash=cash,
        currency=Currency("USD"),
        idempotency_key=key,
        correlation_id="correlation-001",
        request_id="request-001",
    )


def _trade(account, instrument, instant, *, key="order-key-001", side="buy", quantity="2"):
    return PaperTradeRequest(
        account_id=account.account_id,
        instrument_id=instrument,
        side=PaperOrderSide(side),
        quantity=Quantity(quantity),
        reference_price=Price("100", Currency("USD")),
        price_observed_at=instant,
        idempotency_key=key,
    )


def test_open_account_is_transactional_and_replay_safe(
    operational_store,
    fixed_instant,
    operator_principal,
) -> None:
    service = _service(operational_store, fixed_instant)

    created = _account(service, operator_principal)
    replay = _account(service, operator_principal)

    assert replay == created
    assert service.list_accounts(operator_principal) == (created,)
    with operational_store() as uow:
        assert len(uow.audit.list()) == 1
        assert len(uow.outbox.pending(limit=100, available_at=fixed_instant)) == 1
        assert uow.audit.verify_chain()


def test_idempotency_key_rejects_different_payload(
    operational_store,
    fixed_instant,
    operator_principal,
) -> None:
    service = _service(operational_store, fixed_instant)
    _account(service, operator_principal)

    with pytest.raises(IdempotencyConflictError):
        service.open_account(
            principal=operator_principal,
            name="Different Portfolio",
            initial_cash="10000",
            currency=Currency("USD"),
            idempotency_key="account-key-001",
            correlation_id="correlation-002",
            request_id="request-002",
        )


def test_buy_sell_and_order_replay_preserve_exact_accounting(
    operational_store,
    fixed_instant,
    operator_principal,
) -> None:
    service = _service(
        operational_store,
        fixed_instant,
        spread_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        commission_bps=Decimal("0"),
    )
    account = _account(service, operator_principal)
    instrument = InstrumentId.new()

    buy = service.execute_order(
        principal=operator_principal,
        request=_trade(account, instrument, fixed_instant),
        correlation_id="correlation-buy",
        request_id="request-buy",
    )
    replay = service.execute_order(
        principal=operator_principal,
        request=_trade(account, instrument, fixed_instant),
        correlation_id="correlation-replay",
        request_id="request-replay",
    )
    sell_request = _trade(
        buy.account,
        instrument,
        fixed_instant,
        key="order-key-002",
        side="sell",
        quantity="1",
    )
    sell = service.execute_order(
        principal=operator_principal,
        request=sell_request,
        correlation_id="correlation-sell",
        request_id="request-sell",
    )

    assert replay.order.order_id == buy.order.order_id
    assert buy.account.cash.amount == Decimal("9800")
    assert sell.account.cash.amount == Decimal("9900")
    assert sell.account.position(instrument).quantity.value == Decimal("1")
    assert len(service.list_orders(operator_principal, account.account_id)) == 2


def test_service_rejects_stale_future_oversized_and_short_orders(
    operational_store,
    fixed_instant,
    operator_principal,
) -> None:
    service = _service(
        operational_store,
        fixed_instant,
        maximum_order_notional=Decimal("150"),
        maximum_price_age=timedelta(minutes=5),
    )
    account = _account(service, operator_principal)
    instrument = InstrumentId.new()

    with pytest.raises(PaperTradingError, match="future"):
        service.execute_order(
            principal=operator_principal,
            request=_trade(
                account,
                instrument,
                fixed_instant.plus(timedelta(seconds=1)),
            ),
            correlation_id="c-future",
            request_id="r-future",
        )
    stale = PaperTradeRequest(
        account.account_id,
        instrument,
        PaperOrderSide.BUY,
        Quantity("1"),
        Price("100", Currency("USD")),
        fixed_instant.plus(timedelta(minutes=-6)),
        "order-key-stale",
    )
    with pytest.raises(PaperTradingError, match="stale"):
        service.execute_order(
            principal=operator_principal,
            request=stale,
            correlation_id="c-stale",
            request_id="r-stale",
        )
    with pytest.raises(PaperTradingError, match="maximum notional"):
        service.execute_order(
            principal=operator_principal,
            request=_trade(account, instrument, fixed_instant, quantity="2"),
            correlation_id="c-large",
            request_id="r-large",
        )
    with pytest.raises(PaperTradingError, match="Short selling"):
        service.execute_order(
            principal=operator_principal,
            request=_trade(
                account,
                instrument,
                fixed_instant,
                key="order-key-short",
                side="sell",
                quantity="1",
            ),
            correlation_id="c-short",
            request_id="r-short",
        )


def test_account_access_is_owner_scoped_with_auditor_and_admin_exceptions(
    operational_store,
    fixed_instant,
    operator_principal,
) -> None:
    service = _service(operational_store, fixed_instant)
    account = _account(service, operator_principal)
    other = Principal(
        "operator-2",
        "Other Operator",
        frozenset({PrincipalRole.VIEWER, PrincipalRole.OPERATOR}),
    )
    auditor = Principal(
        "auditor-1",
        "Auditor",
        frozenset({PrincipalRole.AUDITOR}),
    )
    admin = Principal("admin-1", "Admin", frozenset({PrincipalRole.ADMIN}))

    with pytest.raises(AuthorizationError):
        service.get_account(other, account.account_id)
    assert service.get_account(auditor, account.account_id) == account
    assert service.get_account(admin, account.account_id) == account
    assert service.list_accounts(auditor) == (account,)
    assert service.list_accounts(other) == ()


def test_policy_validation() -> None:
    with pytest.raises(ValueError, match="negative"):
        PaperTradingPolicy(spread_bps=Decimal("-1"))
    with pytest.raises(ValueError, match="positive"):
        PaperTradingPolicy(maximum_order_notional=Decimal("0"))
    with pytest.raises(ValueError, match="time"):
        PaperTradingPolicy(maximum_price_age=timedelta(0))
