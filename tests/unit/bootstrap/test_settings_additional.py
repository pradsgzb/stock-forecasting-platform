from pathlib import Path

import pytest
from pydantic import ValidationError

from stock_predictor.bootstrap.settings import PlatformSettings


def test_market_settings_reject_duplicate_and_missing_default() -> None:
    exchange = {
        "mic": "XNYS",
        "name": "NYSE",
        "country_code": "US",
        "timezone_name": "America/New_York",
        "calendar_name": "XNYS",
    }
    with pytest.raises(ValidationError, match="must be unique"):
        PlatformSettings.model_validate(
            {"market": {"default_exchange_mic": "XNYS", "exchanges": [exchange, exchange]}}
        )
    with pytest.raises(ValidationError, match="must be present"):
        PlatformSettings.model_validate(
            {"market": {"default_exchange_mic": "XBOM", "exchanges": [exchange]}}
        )


def test_directory_secret_backend_requires_directory() -> None:
    with pytest.raises(ValidationError, match="requires security.secret_directory"):
        PlatformSettings.model_validate({"security": {"secret_backend": "directory"}})


def test_production_live_trading_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Live trading"):
        PlatformSettings.model_validate(
            {
                "app": {"environment": "production"},
                "features": {"enable_future_live_trading": True},
            }
        )


def test_load_settings_reads_explicit_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SP_APP__ENVIRONMENT=integration\n", encoding="utf-8")

    from stock_predictor.bootstrap.settings import load_settings

    assert load_settings(env_file).app.environment.value == "integration"
