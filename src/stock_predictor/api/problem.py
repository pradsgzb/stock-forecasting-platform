"""RFC 9457-style problem responses with controlled error disclosure."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from stock_predictor.domain.common.errors import (
    AuthenticationError,
    AuthorizationError,
    DomainConflictError,
    DomainError,
    DomainNotFoundError,
    DomainValidationError,
    IdempotencyConflictError,
)

_LOGGER = logging.getLogger(__name__)


def _problem(
    request: Request,
    *,
    status: int,
    title: str,
    detail: str,
    error_type: str,
    headers: dict[str, str] | None = None,
    extensions: dict[str, object] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "type": f"urn:stock-predictor:problem:{error_type}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": str(request.scope.get("request_id", "unknown")),
    }
    if extensions:
        body.update(extensions)
    return JSONResponse(
        body,
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authentication_handler(
        request: Request,
        exc: AuthenticationError,
    ) -> JSONResponse:
        return _problem(
            request,
            status=HTTPStatus.UNAUTHORIZED,
            title="Authentication required",
            detail=str(exc),
            error_type="authentication-required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_handler(
        request: Request,
        exc: AuthorizationError,
    ) -> JSONResponse:
        return _problem(
            request,
            status=HTTPStatus.FORBIDDEN,
            title="Access denied",
            detail=str(exc),
            error_type="access-denied",
        )

    @app.exception_handler(DomainNotFoundError)
    async def not_found_handler(
        request: Request,
        exc: DomainNotFoundError,
    ) -> JSONResponse:
        return _problem(
            request,
            status=HTTPStatus.NOT_FOUND,
            title="Resource not found",
            detail=str(exc),
            error_type="not-found",
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_handler(
        request: Request,
        exc: IdempotencyConflictError,
    ) -> JSONResponse:
        return _problem(
            request,
            status=HTTPStatus.CONFLICT,
            title="Idempotency conflict",
            detail=str(exc),
            error_type="idempotency-conflict",
        )

    @app.exception_handler(DomainConflictError)
    async def conflict_handler(
        request: Request,
        exc: DomainConflictError,
    ) -> JSONResponse:
        return _problem(
            request,
            status=HTTPStatus.CONFLICT,
            title="State conflict",
            detail=str(exc),
            error_type="state-conflict",
        )

    @app.exception_handler(DomainValidationError)
    async def domain_validation_handler(
        request: Request,
        exc: DomainValidationError,
    ) -> JSONResponse:
        return _problem(
            request,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            title="Domain validation failed",
            detail=str(exc),
            error_type="domain-validation",
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return _problem(
            request,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            title="Operation rejected",
            detail=str(exc),
            error_type="operation-rejected",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = []
        for item in exc.errors():
            errors.append(
                {
                    "location": [str(part) for part in item.get("loc", ())],
                    "message": str(item.get("msg", "Invalid value")),
                    "type": str(item.get("type", "validation_error")),
                }
            )
        return _problem(
            request,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            title="Request validation failed",
            detail="One or more request fields are invalid",
            error_type="request-validation",
            extensions={"errors": errors},
        )

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        _LOGGER.exception(
            "Unhandled API exception",
            extra={"request_id": request.scope.get("request_id", "unknown")},
        )
        return _problem(
            request,
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            title="Internal server error",
            detail="The request could not be completed",
            error_type="internal-error",
        )
