"""ASGI middleware for correlation, security, limits, tracing, and metrics."""

from __future__ import annotations

import re
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, MutableMapping
from threading import RLock
from typing import Any, TypeAlias
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from stock_predictor.api.context import bind_request_context, reset_request_context
from stock_predictor.ports.telemetry import Telemetry

Scope: TypeAlias = MutableMapping[str, Any]
Message: TypeAlias = MutableMapping[str, Any]
Receive: TypeAlias = Callable[[], Awaitable[Message]]
Send: TypeAlias = Callable[[Message], Awaitable[None]]
AsgiApp: TypeAlias = Callable[[Scope, Receive, Send], Awaitable[None]]

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def _header(scope: Scope, name: bytes) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == name:
            return raw_value.decode("latin-1").strip()
    return None


class RequestContextMiddleware:
    def __init__(self, app: AsgiApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        supplied = _header(scope, b"x-request-id")
        request_id = supplied if supplied and _REQUEST_ID.fullmatch(supplied) else str(uuid4())
        correlation = _header(scope, b"x-correlation-id")
        correlation_id = (
            correlation
            if correlation and _REQUEST_ID.fullmatch(correlation)
            else request_id
        )
        scope["request_id"] = request_id
        scope["correlation_id"] = correlation_id
        tokens = bind_request_context(request_id, correlation_id)

        async def send_with_context(message: Message) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                headers.append((b"x-correlation-id", correlation_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_context)
        finally:
            reset_request_context(tokens)


class RequestBodyLimitMiddleware:
    def __init__(self, app: AsgiApp, *, maximum_bytes: int) -> None:
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        self._app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        content_length = _header(scope, b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._maximum_bytes:
                    await _plain_response(send, 413, b"Request body exceeds configured limit")
                    return
            except ValueError:
                await _plain_response(send, 400, b"Content-Length header is invalid")
                return
        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                consumed += len(body)
                if consumed > self._maximum_bytes:
                    raise _RequestTooLargeError
            return message

        try:
            await self._app(scope, limited_receive, send)
        except _RequestTooLargeError:
            await _plain_response(send, 413, b"Request body exceeds configured limit")


class _RequestTooLargeError(RuntimeError):
    pass


class SecurityHeadersMiddleware:
    def __init__(self, app: AsgiApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def secure_send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    (
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'none'; frame-ancestors 'none'; "
                            b"base-uri 'none'; form-action 'self'",
                        ),
                        (
                            b"permissions-policy",
                            b"camera=(), microphone=(), geolocation=(), payment=()",
                        ),
                        (b"cache-control", b"no-store"),
                    )
                )
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, secure_send)


class InMemoryRateLimitMiddleware:
    """Single-process reference limiter; managed deployments use a shared adapter."""

    def __init__(
        self,
        app: AsgiApp,
        *,
        requests: int,
        window_seconds: int,
        maximum_clients: int,
    ) -> None:
        if requests <= 0 or window_seconds <= 0 or maximum_clients <= 0:
            raise ValueError("Rate-limit values must be positive")
        self._app = app
        self._requests = requests
        self._window = float(window_seconds)
        self._maximum_clients = maximum_clients
        self._seen: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = RLock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        key = str(client[0]) if isinstance(client, tuple) and client else "unknown"
        now = time.monotonic()
        with self._lock:
            history = self._seen.pop(key, deque())
            while history and history[0] <= now - self._window:
                history.popleft()
            self._seen[key] = history
            while len(self._seen) > self._maximum_clients:
                self._seen.popitem(last=False)
            if len(history) >= self._requests:
                await _plain_response(
                    send,
                    429,
                    b"Request rate limit exceeded",
                    extra_headers=((b"retry-after", str(int(self._window)).encode()),),
                )
                return
            history.append(now)
        await self._app(scope, receive, send)


class ObservabilityMiddleware:
    def __init__(self, app: AsgiApp, telemetry: Telemetry, service_name: str) -> None:
        self._app = app
        self._telemetry = telemetry
        self._tracer = trace.get_tracer(service_name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500
        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", "/unmatched"))

        async def observed_send(message: Message) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        with self._tracer.start_as_current_span("http.request") as span:
            span.set_attribute("http.request.method", method)
            span.set_attribute("url.path", path)
            span.set_attribute("request.id", str(scope.get("request_id", "unknown")))
            try:
                await self._app(scope, receive, observed_send)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                route = scope.get("route")
                route_path = str(getattr(route, "path", "/unmatched"))
                duration = time.perf_counter() - started
                span.set_attribute("http.response.status_code", status_code)
                span.set_attribute("http.route", route_path)
                self._telemetry.observe_http_request(
                    method=method,
                    route=route_path,
                    status_code=status_code,
                    duration_seconds=duration,
                )


async def _plain_response(
    send: Send,
    status: int,
    body: bytes,
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain; charset=utf-8"), *extra_headers],
        }
    )
    await send({"type": "http.response.body", "body": body})
