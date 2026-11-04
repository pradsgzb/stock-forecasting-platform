"""Exact API contracts; financial decimals are serialized as strings."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthCheckResponse(ApiModel):
    component: str
    state: str
    detail: str
    latency_milliseconds: str
    checked_at: str


class HealthResponse(ApiModel):
    state: str
    checks: list[HealthCheckResponse]


class SystemInfoResponse(ApiModel):
    name: str
    version: str
    environment: str
    paper_trading_only: bool
    live_trading_available: bool


class OpenPaperAccountRequest(ApiModel):
    name: Annotated[str, Field(min_length=2, max_length=80)]
    initial_cash: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,18})?$")]
    currency: Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]


class PaperPositionResponse(ApiModel):
    instrument_id: str
    quantity: str
    average_price: str
    currency: str


class PaperAccountResponse(ApiModel):
    account_id: str
    owner_subject: str
    name: str
    currency: str
    cash: str
    realized_pnl: str
    revision: int
    created_at: str
    updated_at: str
    positions: list[PaperPositionResponse]


class ExecutePaperOrderRequest(ApiModel):
    instrument_id: str
    side: Annotated[str, Field(pattern=r"^(buy|sell)$")]
    quantity: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,18})?$")]
    reference_price: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,18})?$")]
    currency: Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
    price_observed_at: datetime


class PaperOrderResponse(ApiModel):
    order_id: str
    account_id: str
    instrument_id: str
    side: str
    quantity: str
    reference_price: str
    execution_price: str | None = None
    commission: str | None = None
    currency: str
    submitted_at: str
    status: str


class AuditEventResponse(ApiModel):
    event_id: str
    sequence: int
    occurred_at: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    correlation_id: str
    request_id: str
    reason: str
    attributes: dict[str, object]
    previous_hash: str | None
    event_hash: str


class MonitoringAlertResponse(ApiModel):
    alert_id: str
    model_version_id: str
    severity: int
    category: str
    title: str
    detail: str
    evidence_reference: str
    raised_at: str


class PredictionResponse(ApiModel):
    prediction_id: str
    instrument_id: str
    model_version_id: str
    as_of: str
    decision_cutoff: str
    generated_at: str
    predicted_value: str
    positive_probability: str | None
    expected_volatility: str | None
    rank: str | None
    confidence: str | None
    fingerprint: str
