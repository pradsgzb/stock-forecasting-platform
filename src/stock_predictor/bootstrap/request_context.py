"""Process-local request identifiers for structured logging and tracing."""

from __future__ import annotations

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def bind_request_context(request_id: str, correlation_id: str) -> tuple[Token[str | None], ...]:
    return (_request_id.set(request_id), _correlation_id.set(correlation_id))


def reset_request_context(tokens: tuple[Token[str | None], ...]) -> None:
    _request_id.reset(tokens[0])
    _correlation_id.reset(tokens[1])


def current_request_id() -> str | None:
    return _request_id.get()


def current_correlation_id() -> str | None:
    return _correlation_id.get()
