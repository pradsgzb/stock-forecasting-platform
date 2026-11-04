"""Structured logging with correlation metadata and defensive redaction."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from opentelemetry import trace

from stock_predictor.bootstrap.request_context import (
    current_correlation_id,
    current_request_id,
)
from stock_predictor.bootstrap.settings import LogLevel, RuntimeEnvironment

_SENSITIVE = re.compile(
    r"(?i)(authorization|bearer|token|api[_-]?key|password|secret)"
    r"(\s*[=:]\s*|\s+)([^\s,;]+)"
)


def redact_sensitive_text(value: str) -> str:
    """Remove common credential forms without attempting to parse business payloads."""
    return _SENSITIVE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_text(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Format one operational event per line without arbitrary record attributes."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
        }
        request_id = current_request_id()
        correlation_id = current_correlation_id()
        if request_id is not None:
            payload["request_id"] = request_id
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")
        if record.exc_info:
            payload["exception"] = redact_sensitive_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: LogLevel, environment: RuntimeEnvironment) -> None:
    """Configure process logging once at the entry-point boundary."""
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    if environment in {RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION}:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.value)
