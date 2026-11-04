import pytest
from pydantic import SecretStr, ValidationError

from stock_predictor.bootstrap.settings import PlatformSettings, RuntimeEnvironment


def test_default_settings_are_safe() -> None:
    settings = PlatformSettings(_env_file=None)

    assert settings.app.environment is RuntimeEnvironment.LOCAL
    assert settings.features.enable_future_live_trading is False
    assert settings.safe_summary()["market_data_api_key_configured"] is False


def test_environment_override_uses_nested_delimiter(monkeypatch) -> None:
    monkeypatch.setenv("SP_APP__ENVIRONMENT", "staging")
    monkeypatch.setenv("SP_APP__LOG_LEVEL", "WARNING")

    settings = PlatformSettings(_env_file=None)

    assert settings.app.environment is RuntimeEnvironment.STAGING
    assert settings.app.log_level.value == "WARNING"


def test_production_debug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Debug mode is prohibited"):
        PlatformSettings.model_validate(
            {"app": {"environment": "production", "debug": True}}
        )


def test_secret_is_redacted() -> None:
    settings = PlatformSettings.model_validate(
        {"security": {"market_data_api_key": SecretStr("super-secret")}}
    )

    assert "super-secret" not in repr(settings)
    assert settings.safe_summary()["market_data_api_key_configured"] is True


def test_mlops_defaults_require_human_governance() -> None:
    settings = PlatformSettings(_env_file=None)

    assert settings.features.enable_future_online_inference is False
    assert settings.continuous_training.allow_automatic_promotion is False
    assert settings.model_registry.required_approval_roles == (
        "model_validator",
        "risk_owner",
        "deployment_approver",
    )
    assert settings.safe_summary()["automatic_model_promotion_enabled"] is False


def test_model_registry_settings_normalize_and_validate_roles() -> None:
    settings = PlatformSettings.model_validate(
        {
            "model_registry": {
                "required_gate_names": [" Artifact_Verified "],
                "required_approval_roles": [
                    " MODEL_VALIDATOR ",
                    " RISK_OWNER ",
                    " DEPLOYMENT_APPROVER ",
                ],
            }
        }
    )

    assert settings.model_registry.required_gate_names == ("artifact_verified",)
    assert settings.model_registry.required_approval_roles == (
        "model_validator",
        "risk_owner",
        "deployment_approver",
    )

    with pytest.raises(ValidationError, match="Unsupported model-registry"):
        PlatformSettings.model_validate(
            {"model_registry": {"required_approval_roles": ["administrator"]}}
        )


def test_monitoring_threshold_order_is_enforced() -> None:
    with pytest.raises(ValidationError, match="critical thresholds"):
        PlatformSettings.model_validate(
            {"monitoring": {"psi_warning": "0.25", "psi_critical": "0.10"}}
        )

    with pytest.raises(ValidationError, match="directional accuracy"):
        PlatformSettings.model_validate(
            {
                "monitoring": {
                    "directional_accuracy_warning": "0.45",
                    "directional_accuracy_critical": "0.50",
                }
            }
        )


def test_api_rate_limit_state_has_a_bounded_default() -> None:
    settings = PlatformSettings(_env_file=None)

    assert settings.api.rate_limit_maximum_clients == 10_000


def test_managed_api_runtime_requires_asymmetric_jwt_verification() -> None:
    settings = PlatformSettings.model_validate(
        {
            "app": {"environment": "staging"},
            "database": {"url": "postgresql+psycopg://user:pass@db/app"},
            "api": {
                "docs_enabled": False,
                "jwt_algorithms": ["HS256"],
                "jwt_verification_key": "shared-secret",
            },
        }
    )

    with pytest.raises(ValueError, match="asymmetric JWT"):
        settings.validate_api_runtime()
