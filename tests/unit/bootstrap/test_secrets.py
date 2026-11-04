from pathlib import Path

import pytest

from stock_predictor.bootstrap.secrets import (
    DirectorySecretProvider,
    EnvironmentSecretProvider,
    SecretError,
    SecretNotFoundError,
)


def test_environment_secret_provider(monkeypatch) -> None:
    monkeypatch.setenv("SP_SECRET_VENDOR_TOKEN", "classified")

    secret = EnvironmentSecretProvider().get("VENDOR_TOKEN")

    assert secret.get_secret_value() == "classified"
    assert "classified" not in repr(secret)


def test_directory_provider_reads_only_valid_names(tmp_path: Path) -> None:
    (tmp_path / "VENDOR_TOKEN").write_text("classified\n", encoding="utf-8")
    provider = DirectorySecretProvider(tmp_path)

    assert provider.get("VENDOR_TOKEN").get_secret_value() == "classified"
    with pytest.raises(SecretError, match="Invalid secret name"):
        provider.get("../escape")


def test_missing_secret_is_explicit(monkeypatch) -> None:
    monkeypatch.delenv("SP_SECRET_MISSING", raising=False)
    with pytest.raises(SecretNotFoundError):
        EnvironmentSecretProvider().get("MISSING")
