from pathlib import Path

import pytest
from pydantic import ValidationError

from stock_predictor.bootstrap.settings import PlatformSettings


def test_api_verification_key_can_be_loaded_from_file(tmp_path: Path) -> None:
    key = tmp_path / "public.pem"
    key.write_text("PUBLIC KEY CONTENT\n", encoding="utf-8")
    settings = PlatformSettings.model_validate(
        {"api": {"jwt_verification_key_path": key}}
    )

    assert settings.api_verification_key() == "PUBLIC KEY CONTENT"
    assert settings.safe_summary()["api_jwt_key_configured"] is True


def test_api_verification_key_sources_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="either an inline JWT key"):
        PlatformSettings.model_validate(
            {
                "api": {
                    "jwt_verification_key": "inline",
                    "jwt_verification_key_path": tmp_path / "key.pem",
                }
            }
        )


def test_api_verification_key_file_must_exist_and_not_be_empty(tmp_path: Path) -> None:
    missing = PlatformSettings.model_validate(
        {"api": {"jwt_verification_key_path": tmp_path / "missing.pem"}}
    )
    with pytest.raises(ValueError, match="Unable to read"):
        missing.api_verification_key()

    empty_path = tmp_path / "empty.pem"
    empty_path.write_text("  \n", encoding="utf-8")
    empty = PlatformSettings.model_validate(
        {"api": {"jwt_verification_key_path": empty_path}}
    )
    with pytest.raises(ValueError, match="empty"):
        empty.api_verification_key()
