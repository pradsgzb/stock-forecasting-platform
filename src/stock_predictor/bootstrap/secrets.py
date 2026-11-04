"""Secret-provider abstractions for local and future managed secret stores."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import SecretStr

from stock_predictor.bootstrap.settings import SecretBackend, SecuritySettings

_SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class SecretError(RuntimeError):
    """Base exception for secret retrieval failures."""


class SecretNotFoundError(SecretError):
    """Raised when a required secret is unavailable."""


@runtime_checkable
class SecretProvider(Protocol):
    """Retrieves secrets without exposing a provider-specific API to application code."""

    def get(self, name: str) -> SecretStr:
        """Return a secret by canonical name."""
        ...


class EnvironmentSecretProvider:
    """Reads secrets from environment variables with a fixed prefix."""

    __slots__ = ("_prefix",)

    def __init__(self, prefix: str = "SP_SECRET_") -> None:
        self._prefix = prefix

    def get(self, name: str) -> SecretStr:
        canonical = _validate_secret_name(name)
        key = f"{self._prefix}{canonical}"
        value = os.getenv(key)
        if value is None or not value:
            msg = f"Required secret is not configured: {canonical}"
            raise SecretNotFoundError(msg)
        return SecretStr(value)


class DirectorySecretProvider:
    """Reads one secret per file, compatible with container secret mounts."""

    __slots__ = ("_directory",)

    def __init__(self, directory: Path) -> None:
        self._directory = directory.resolve()

    def get(self, name: str) -> SecretStr:
        canonical = _validate_secret_name(name)
        candidate = (self._directory / canonical).resolve()
        if candidate.parent != self._directory:
            msg = "Secret path escaped the configured directory"
            raise SecretError(msg)
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            msg = f"Required secret is not configured: {canonical}"
            raise SecretNotFoundError(msg) from exc
        if not value:
            msg = f"Configured secret is empty: {canonical}"
            raise SecretNotFoundError(msg)
        return SecretStr(value)


def _validate_secret_name(name: str) -> str:
    canonical = name.strip().upper()
    if not _SECRET_NAME_PATTERN.fullmatch(canonical):
        msg = f"Invalid secret name: {name!r}"
        raise SecretError(msg)
    return canonical


def build_secret_provider(settings: SecuritySettings) -> SecretProvider:
    """Build the configured secret provider."""
    if settings.secret_backend is SecretBackend.ENVIRONMENT:
        return EnvironmentSecretProvider()
    if settings.secret_directory is None:  # Defensive; settings validation normally catches it.
        msg = "Directory secret backend requires a directory"
        raise SecretError(msg)
    return DirectorySecretProvider(settings.secret_directory)
