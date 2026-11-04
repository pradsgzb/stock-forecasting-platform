from pathlib import Path

import pytest

from stock_predictor.bootstrap.secrets import (
    DirectorySecretProvider,
    EnvironmentSecretProvider,
    SecretError,
    SecretNotFoundError,
    build_secret_provider,
)
from stock_predictor.bootstrap.settings import PlatformSettings


def test_directory_provider_reports_missing_and_empty(tmp_path: Path) -> None:
    provider = DirectorySecretProvider(tmp_path)
    with pytest.raises(SecretNotFoundError):
        provider.get("MISSING")

    (tmp_path / "EMPTY").write_text("\n", encoding="utf-8")
    with pytest.raises(SecretNotFoundError, match="empty"):
        provider.get("EMPTY")


def test_build_secret_provider_selects_backend(tmp_path: Path) -> None:
    environment_settings = PlatformSettings.model_validate({}).security
    assert isinstance(build_secret_provider(environment_settings), EnvironmentSecretProvider)

    directory_settings = PlatformSettings.model_validate(
        {"security": {"secret_backend": "directory", "secret_directory": tmp_path}}
    ).security
    assert isinstance(build_secret_provider(directory_settings), DirectorySecretProvider)


def test_invalid_secret_name_is_rejected() -> None:
    with pytest.raises(SecretError):
        EnvironmentSecretProvider().get("lowercase-not-valid?")
