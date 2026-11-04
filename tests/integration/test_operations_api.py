from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stock_predictor.adapters.persistence.sqlalchemy_store import SqlAlchemyOperationalStore
from stock_predictor.adapters.repositories.in_memory_instrument_repository import (
    InMemoryInstrumentRepository,
)
from stock_predictor.adapters.security.jwt_authenticator import StaticBearerAuthenticator
from stock_predictor.api.app import create_api_app
from stock_predictor.bootstrap.container import ApplicationContainer, build_container
from stock_predictor.bootstrap.settings import PlatformSettings
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.security.identity import Principal, PrincipalRole

pytestmark = [pytest.mark.integration, pytest.mark.security]


@dataclass
class ApiFixture:
    client: TestClient
    container: ApplicationContainer
    store: SqlAlchemyOperationalStore
    tokens: dict[str, str]
    instrument_id: str

    def close(self) -> None:
        self.client.close()
        self.store.dispose()


def _principal(subject: str, *roles: PrincipalRole) -> Principal:
    return Principal(subject, subject.replace("-", " ").title(), frozenset(roles))


def _build_api(tmp_path: Path, sample_instrument, *, rate_limit: int = 1000) -> ApiFixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = SqlAlchemyOperationalStore(
        f"sqlite+pysqlite:///{tmp_path / 'operations.db'}"
    )
    store.create_schema_for_testing()
    instruments = InMemoryInstrumentRepository()
    instruments.add(sample_instrument)
    settings = PlatformSettings(
        _env_file=None,
        app={"environment": "test"},
        storage={"data_root": tmp_path / "data"},
        database={"url": f"sqlite+pysqlite:///{tmp_path / 'operations.db'}"},
        api={
            "rate_limit_requests": rate_limit,
            "rate_limit_window_seconds": 60,
            "request_body_limit_bytes": 1024,
            "docs_enabled": True,
        },
    )
    from datetime import UTC, datetime

    from stock_predictor.domain.common.temporal import UtcInstant

    container = build_container(
        settings,
        clock=FixedClock(UtcInstant(datetime(2026, 1, 2, 15, 30, tzinfo=UTC))),
        instruments=instruments,
        operational_store=store,
    )
    principals = {
        "operator-token": _principal(
            "operator-1",
            PrincipalRole.VIEWER,
            PrincipalRole.OPERATOR,
        ),
        "viewer-token": _principal("viewer-1", PrincipalRole.VIEWER),
        "other-token": _principal(
            "operator-2",
            PrincipalRole.VIEWER,
            PrincipalRole.OPERATOR,
        ),
        "auditor-token": _principal("auditor-1", PrincipalRole.AUDITOR),
        "metrics-token": _principal("metrics-1", PrincipalRole.METRICS_READER),
        "admin-token": _principal("admin-1", PrincipalRole.ADMIN),
    }
    app = create_api_app(container, StaticBearerAuthenticator(principals))
    return ApiFixture(
        TestClient(app, raise_server_exceptions=False),
        container,
        store,
        {key: key for key in principals},
        str(sample_instrument.instrument_id),
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _account_body() -> dict[str, str]:
    return {
        "name": "Research Portfolio",
        "initial_cash": "10000.00",
        "currency": "USD",
    }


def test_secured_api_vertical_slice_and_error_contracts(tmp_path, sample_instrument) -> None:
    api = _build_api(tmp_path, sample_instrument)
    client = api.client
    try:
        live = client.get(
            "/health/live",
            headers={"X-Request-ID": "request-live-001"},
        )
        assert live.status_code == 200
        assert live.json()["state"] == "healthy"
        assert live.headers["x-request-id"] == "request-live-001"
        assert live.headers["x-content-type-options"] == "nosniff"
        assert live.headers["cache-control"] == "no-store"

        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"][0]["component"] == "operational_database"

        unauthenticated = client.get("/api/v1/system")
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["www-authenticate"] == "Bearer"
        assert unauthenticated.headers["content-type"].startswith(
            "application/problem+json"
        )

        system = client.get("/api/v1/system", headers=_auth("viewer-token"))
        assert system.status_code == 200
        assert system.json()["paper_trading_only"] is True
        assert system.json()["live_trading_available"] is False

        forbidden_metrics = client.get("/metrics", headers=_auth("viewer-token"))
        assert forbidden_metrics.status_code == 403
        metrics = client.get("/metrics", headers=_auth("metrics-token"))
        assert metrics.status_code == 200
        assert b"http_requests_total" in metrics.content

        invalid = client.post(
            "/api/v1/paper/accounts",
            headers={**_auth("operator-token"), "Idempotency-Key": "account-key-001"},
            json={**_account_body(), "unexpected": "rejected"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["type"].endswith("request-validation")

        created = client.post(
            "/api/v1/paper/accounts",
            headers={
                **_auth("operator-token"),
                "Idempotency-Key": "account-key-001",
                "X-Correlation-ID": "correlation-account-001",
            },
            json=_account_body(),
        )
        assert created.status_code == 201
        account_id = created.json()["account_id"]
        assert created.json()["cash"] == "10000.00"

        replay = client.post(
            "/api/v1/paper/accounts",
            headers={**_auth("operator-token"), "Idempotency-Key": "account-key-001"},
            json=_account_body(),
        )
        assert replay.status_code == 201
        assert replay.json()["account_id"] == account_id

        conflict = client.post(
            "/api/v1/paper/accounts",
            headers={**_auth("operator-token"), "Idempotency-Key": "account-key-001"},
            json={**_account_body(), "initial_cash": "9000"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["type"].endswith("idempotency-conflict")

        listed = client.get(
            "/api/v1/paper/accounts",
            headers=_auth("operator-token"),
        )
        assert [item["account_id"] for item in listed.json()] == [account_id]
        assert client.get(
            "/api/v1/paper/accounts",
            headers=_auth("other-token"),
        ).json() == []

        denied = client.get(
            f"/api/v1/paper/accounts/{account_id}",
            headers=_auth("other-token"),
        )
        assert denied.status_code == 403

        order = client.post(
            f"/api/v1/paper/accounts/{account_id}/orders",
            headers={**_auth("operator-token"), "Idempotency-Key": "order-key-001"},
            json={
                "instrument_id": api.instrument_id,
                "side": "buy",
                "quantity": "2",
                "reference_price": "100",
                "currency": "USD",
                "price_observed_at": "2026-01-02T15:30:00Z",
            },
        )
        assert order.status_code == 201
        assert order.json()["status"] == "filled"
        assert order.json()["execution_price"] is not None

        orders = client.get(
            f"/api/v1/paper/accounts/{account_id}/orders",
            headers=_auth("operator-token"),
        )
        assert orders.status_code == 200
        assert len(orders.json()) == 1
        assert orders.json()[0]["execution_price"] is None

        missing_instrument = client.post(
            f"/api/v1/paper/accounts/{account_id}/orders",
            headers={**_auth("operator-token"), "Idempotency-Key": "order-key-002"},
            json={
                "instrument_id": "00000000-0000-0000-0000-000000000001",
                "side": "buy",
                "quantity": "1",
                "reference_price": "100",
                "currency": "USD",
                "price_observed_at": "2026-01-02T15:30:00Z",
            },
        )
        assert missing_instrument.status_code == 404

        audit = client.get("/api/v1/audit/events", headers=_auth("auditor-token"))
        assert audit.status_code == 200
        assert len(audit.json()) == 2
        assert audit.json()[1]["previous_hash"] == audit.json()[0]["event_hash"]

        alerts = client.get(
            "/api/v1/monitoring/alerts",
            headers=_auth("viewer-token"),
        )
        assert alerts.status_code == 200 and alerts.json() == []

        missing_prediction = client.get(
            "/api/v1/predictions/00000000-0000-0000-0000-000000000001",
            headers=_auth("viewer-token"),
        )
        assert missing_prediction.status_code == 404

        dashboard = client.get("/dashboard", headers=_auth("operator-token"))
        assert dashboard.status_code == 200
        assert "Paper trading only" in dashboard.text
        assert "Research Portfolio" in dashboard.text

        docs = client.get("/openapi.json")
        assert docs.status_code == 200
        assert docs.json()["info"]["title"].startswith("Stock Forecasting")

        bad_host = client.get("/health/live", headers={"Host": "evil.example"})
        assert bad_host.status_code == 400
    finally:
        api.close()


def test_body_limit_and_rate_limit_are_enforced(tmp_path, sample_instrument) -> None:
    api = _build_api(tmp_path, sample_instrument, rate_limit=1)
    try:
        first = api.client.get("/health/live")
        second = api.client.get("/health/live")
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.headers["retry-after"] == "60"
    finally:
        api.close()

    another = _build_api(tmp_path / "body", sample_instrument, rate_limit=100)
    try:
        response = another.client.post(
            "/api/v1/paper/accounts",
            headers={
                **_auth("operator-token"),
                "Idempotency-Key": "account-key-oversized",
            },
            content=b"x" * 2048,
        )
        assert response.status_code == 413
    finally:
        another.close()


def test_unhealthy_readiness_returns_503(tmp_path, sample_instrument) -> None:
    api = _build_api(tmp_path, sample_instrument)

    class UnhealthyStore:
        def health_check(self) -> bool:
            return False

    api.container.health_service._store = UnhealthyStore()
    try:
        response = api.client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["state"] == "unhealthy"
    finally:
        api.close()


def test_unexpected_authenticator_failure_is_sanitized(tmp_path, sample_instrument) -> None:
    api = _build_api(tmp_path, sample_instrument)

    class BrokenAuthenticator:
        def authenticate(self, bearer_token: str) -> Principal:
            del bearer_token
            raise RuntimeError("secret backend detail")

    api.client.close()
    api.client = TestClient(
        create_api_app(api.container, BrokenAuthenticator()),
        raise_server_exceptions=False,
    )
    try:
        response = api.client.get(
            "/api/v1/system",
            headers=_auth("anything"),
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "The request could not be completed"
        assert "secret backend detail" not in response.text
    finally:
        api.close()
