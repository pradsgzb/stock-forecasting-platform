"""FastAPI composition for secured operations and paper-only workflows."""

from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, Response

from stock_predictor import __version__
from stock_predictor.api.dependencies import build_principal_dependency, require_roles
from stock_predictor.api.middleware import (
    InMemoryRateLimitMiddleware,
    ObservabilityMiddleware,
    RequestBodyLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from stock_predictor.api.models import (
    AuditEventResponse,
    ExecutePaperOrderRequest,
    HealthCheckResponse,
    HealthResponse,
    MonitoringAlertResponse,
    OpenPaperAccountRequest,
    PaperAccountResponse,
    PaperOrderResponse,
    PaperPositionResponse,
    PredictionResponse,
    SystemInfoResponse,
)
from stock_predictor.api.problem import install_problem_handlers
from stock_predictor.bootstrap.container import ApplicationContainer
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    PaperAccountId,
    PredictionId,
)
from stock_predictor.domain.common.money import Currency, Price
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import Quantity
from stock_predictor.domain.operations.paper import PaperOrderSide, PaperTradeRequest
from stock_predictor.domain.security.identity import Principal, PrincipalRole
from stock_predictor.ports.authentication import Authenticator


def create_api_app(
    container: ApplicationContainer,
    authenticator: Authenticator,
) -> FastAPI:
    settings = container.settings
    app = FastAPI(
        title="Stock Forecasting Platform Operations API",
        version=__version__,
        docs_url="/docs" if settings.api.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.api.docs_enabled else None,
    )
    app.state.container = container
    principal = build_principal_dependency(authenticator)
    viewer = require_roles(
        principal,
        PrincipalRole.VIEWER,
        PrincipalRole.OPERATOR,
        PrincipalRole.MODEL_APPROVER,
        PrincipalRole.AUDITOR,
        PrincipalRole.ADMIN,
    )
    operator = require_roles(principal, PrincipalRole.OPERATOR, PrincipalRole.ADMIN)
    auditor = require_roles(principal, PrincipalRole.AUDITOR, PrincipalRole.ADMIN)
    metrics_reader = require_roles(
        principal,
        PrincipalRole.METRICS_READER,
        PrincipalRole.ADMIN,
    )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return _health_response(container.health_service.liveness())

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse | Response:
        report = container.health_service.readiness()
        response = _health_response(report)
        if report.state.value == "unhealthy":
            return Response(
                content=response.model_dump_json(),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                media_type="application/json",
            )
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics(
        _principal: Principal = Depends(metrics_reader),
    ) -> Response:
        return Response(
            content=container.telemetry.render(),
            media_type=container.telemetry.content_type,
        )

    @app.get(
        "/api/v1/system",
        response_model=SystemInfoResponse,
        tags=["operations"],
    )
    async def system_info(
        _principal: Principal = Depends(viewer),
    ) -> SystemInfoResponse:
        return SystemInfoResponse(
            name=settings.app.name,
            version=__version__,
            environment=settings.app.environment.value,
            paper_trading_only=True,
            live_trading_available=False,
        )

    @app.post(
        "/api/v1/paper/accounts",
        response_model=PaperAccountResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["paper-trading"],
    )
    async def open_paper_account(
        body: OpenPaperAccountRequest,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        caller: Principal = Depends(operator),
    ) -> PaperAccountResponse:
        account = container.paper_trading_service.open_account(
            principal=caller,
            name=body.name,
            initial_cash=body.initial_cash,
            currency=Currency(body.currency),
            idempotency_key=idempotency_key,
            correlation_id=str(request.scope["correlation_id"]),
            request_id=str(request.scope["request_id"]),
        )
        return _account_response(account)

    @app.get(
        "/api/v1/paper/accounts",
        response_model=list[PaperAccountResponse],
        tags=["paper-trading"],
    )
    async def list_paper_accounts(
        caller: Principal = Depends(viewer),
    ) -> list[PaperAccountResponse]:
        return [
            _account_response(item)
            for item in container.paper_trading_service.list_accounts(caller)
        ]

    @app.get(
        "/api/v1/paper/accounts/{account_id}",
        response_model=PaperAccountResponse,
        tags=["paper-trading"],
    )
    async def get_paper_account(
        account_id: str,
        caller: Principal = Depends(viewer),
    ) -> PaperAccountResponse:
        account = container.paper_trading_service.get_account(
            caller,
            PaperAccountId.parse(account_id),
        )
        return _account_response(account)

    @app.post(
        "/api/v1/paper/accounts/{account_id}/orders",
        response_model=PaperOrderResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["paper-trading"],
    )
    async def execute_paper_order(
        account_id: str,
        body: ExecutePaperOrderRequest,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        caller: Principal = Depends(operator),
    ) -> PaperOrderResponse:
        instrument_id = InstrumentId.parse(body.instrument_id)
        container.instruments.get(instrument_id)
        trade = PaperTradeRequest(
            account_id=PaperAccountId.parse(account_id),
            instrument_id=instrument_id,
            side=PaperOrderSide(body.side),
            quantity=Quantity(body.quantity),
            reference_price=Price(body.reference_price, Currency(body.currency)),
            price_observed_at=UtcInstant(body.price_observed_at),
            idempotency_key=idempotency_key,
        )
        execution = container.paper_trading_service.execute_order(
            principal=caller,
            request=trade,
            correlation_id=str(request.scope["correlation_id"]),
            request_id=str(request.scope["request_id"]),
        )
        return _order_response(execution.order, execution.fill)

    @app.get(
        "/api/v1/paper/accounts/{account_id}/orders",
        response_model=list[PaperOrderResponse],
        tags=["paper-trading"],
    )
    async def list_paper_orders(
        account_id: str,
        caller: Principal = Depends(viewer),
    ) -> list[PaperOrderResponse]:
        orders = container.paper_trading_service.list_orders(
            caller,
            PaperAccountId.parse(account_id),
        )
        return [_order_response(item, None) for item in orders]

    @app.get(
        "/api/v1/audit/events",
        response_model=list[AuditEventResponse],
        tags=["audit"],
    )
    async def audit_events(
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
        _caller: Principal = Depends(auditor),
    ) -> list[AuditEventResponse]:
        with container.operational_store() as uow:
            events = uow.audit.list(limit=limit, after_sequence=after_sequence)
        return [_audit_response(item) for item in events]

    @app.get(
        "/api/v1/monitoring/alerts",
        response_model=list[MonitoringAlertResponse],
        tags=["monitoring"],
    )
    async def monitoring_alerts(
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        _caller: Principal = Depends(viewer),
    ) -> list[MonitoringAlertResponse]:
        alerts = container.monitoring.alerts()[-limit:]
        return [
            MonitoringAlertResponse(
                alert_id=str(item.alert_id),
                model_version_id=str(item.model_version_id),
                severity=int(item.severity),
                category=item.category,
                title=item.title,
                detail=item.detail,
                evidence_reference=item.evidence_reference,
                raised_at=item.raised_at.isoformat(),
            )
            for item in alerts
        ]

    @app.get(
        "/api/v1/predictions/{prediction_id}",
        response_model=PredictionResponse,
        tags=["predictions"],
    )
    async def get_prediction(
        prediction_id: str,
        _caller: Principal = Depends(viewer),
    ) -> PredictionResponse:
        item = container.prediction_ledger.get_prediction(
            PredictionId.parse(prediction_id)
        )
        return PredictionResponse(
            prediction_id=str(item.prediction_id),
            instrument_id=str(item.instrument_id),
            model_version_id=str(item.model_version_id),
            as_of=item.as_of.isoformat(),
            decision_cutoff=item.decision_cutoff.isoformat(),
            generated_at=item.generated_at.isoformat(),
            predicted_value=str(item.predicted_value),
            positive_probability=(
                str(item.positive_probability.value)
                if item.positive_probability is not None
                else None
            ),
            expected_volatility=(
                str(item.expected_volatility)
                if item.expected_volatility is not None
                else None
            ),
            rank=(
                str(item.cross_sectional_rank.value)
                if item.cross_sectional_rank is not None
                else None
            ),
            confidence=(
                str(item.confidence.value) if item.confidence is not None else None
            ),
            fingerprint=item.fingerprint,
        )

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(caller: Principal = Depends(viewer)) -> HTMLResponse:
        accounts = container.paper_trading_service.list_accounts(caller)
        alerts = container.monitoring.alerts()
        rows = "".join(
            "<tr>"
            f"<td>{escape(item.name)}</td>"
            f"<td>{escape(str(item.base_currency))}</td>"
            f"<td>{escape(str(item.cash.amount))}</td>"
            f"<td>{len(item.positions)}</td>"
            "</tr>"
            for item in accounts
        )
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Stock Forecasting Operations</title></head><body>"
            "<h1>Stock Forecasting Operations</h1>"
            f"<p>Environment: {escape(settings.app.environment.value)}</p>"
            f"<p>Active monitoring alerts: {len(alerts)}</p>"
            "<p>Paper trading only. Live brokerage is unavailable.</p>"
            "<table><thead><tr><th>Account</th><th>Currency</th>"
            "<th>Cash</th><th>Positions</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></body></html>"
        )
        return HTMLResponse(body)

    install_problem_handlers(app)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(settings.api.allowed_hosts),
    )
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests=settings.api.rate_limit_requests,
        window_seconds=settings.api.rate_limit_window_seconds,
        maximum_clients=settings.api.rate_limit_maximum_clients,
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        maximum_bytes=settings.api.request_body_limit_bytes,
    )
    app.add_middleware(
        ObservabilityMiddleware,
        telemetry=container.telemetry,
        service_name=settings.observability.service_name,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


def _health_response(report: object) -> HealthResponse:
    from stock_predictor.application.health.service import HealthReport

    if not isinstance(report, HealthReport):
        raise TypeError("Expected HealthReport")
    return HealthResponse(
        state=report.state.value,
        checks=[
            HealthCheckResponse(
                component=item.component,
                state=item.state.value,
                detail=item.detail,
                latency_milliseconds=str(item.latency_milliseconds),
                checked_at=item.checked_at.isoformat(),
            )
            for item in report.checks
        ],
    )


def _account_response(account: object) -> PaperAccountResponse:
    from stock_predictor.domain.operations.paper import PaperAccount

    if not isinstance(account, PaperAccount):
        raise TypeError("Expected PaperAccount")
    return PaperAccountResponse(
        account_id=str(account.account_id),
        owner_subject=account.owner_subject,
        name=account.name,
        currency=str(account.base_currency),
        cash=str(account.cash.amount),
        realized_pnl=str(account.realized_pnl.amount),
        revision=account.revision,
        created_at=account.created_at.isoformat(),
        updated_at=account.updated_at.isoformat(),
        positions=[
            PaperPositionResponse(
                instrument_id=str(item.instrument_id),
                quantity=str(item.quantity.value),
                average_price=str(item.average_price.amount),
                currency=str(item.average_price.currency),
            )
            for item in account.positions
        ],
    )


def _order_response(order: object, fill: object | None) -> PaperOrderResponse:
    from stock_predictor.domain.operations.paper import PaperFill, PaperOrder

    if not isinstance(order, PaperOrder):
        raise TypeError("Expected PaperOrder")
    if fill is not None and not isinstance(fill, PaperFill):
        raise TypeError("Expected PaperFill")
    return PaperOrderResponse(
        order_id=str(order.order_id),
        account_id=str(order.account_id),
        instrument_id=str(order.instrument_id),
        side=order.side.value,
        quantity=str(order.quantity.value),
        reference_price=str(order.reference_price.amount),
        execution_price=str(fill.execution_price.amount) if fill else None,
        commission=str(fill.commission.amount) if fill else None,
        currency=str(order.reference_price.currency),
        submitted_at=order.submitted_at.isoformat(),
        status=order.status.value,
    )


def _audit_response(event: object) -> AuditEventResponse:
    from stock_predictor.domain.operations.records import AuditEvent

    if not isinstance(event, AuditEvent):
        raise TypeError("Expected AuditEvent")
    return AuditEventResponse(
        event_id=str(event.event_id),
        sequence=event.sequence,
        occurred_at=event.occurred_at.isoformat(),
        actor_id=event.actor_id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        outcome=event.outcome.value,
        correlation_id=event.correlation_id,
        request_id=event.request_id,
        reason=event.reason,
        attributes=event.attributes.as_dict(),
        previous_hash=event.previous_hash,
        event_hash=event.event_hash,
    )
