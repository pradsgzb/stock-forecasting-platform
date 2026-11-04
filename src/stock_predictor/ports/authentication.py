"""Caller authentication port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.security.identity import Principal


@runtime_checkable
class Authenticator(Protocol):
    def authenticate(self, bearer_token: str) -> Principal:
        ...
