"""Compatibility exports for request correlation context."""

from stock_predictor.bootstrap.request_context import (
    bind_request_context,
    current_correlation_id as correlation_id,
    current_request_id as request_id,
    reset_request_context,
)

__all__ = [
    "bind_request_context",
    "correlation_id",
    "request_id",
    "reset_request_context",
]
