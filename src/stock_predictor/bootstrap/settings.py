"""Typed application settings loaded at the process boundary."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeEnvironment(StrEnum):
    """Supported runtime environments."""

    LOCAL = "local"
    TEST = "test"
    INTEGRATION = "integration"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported logging thresholds."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class SecretBackend(StrEnum):
    """Available secret-provider implementations in this foundation."""

    ENVIRONMENT = "environment"
    DIRECTORY = "directory"


class ImmutableModel(BaseModel):
    """Base model for immutable nested settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ApplicationSettings(ImmutableModel):
    """Process-level behavior."""

    name: str = "stock-forecasting-platform"
    environment: RuntimeEnvironment = RuntimeEnvironment.LOCAL
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO


class ExchangeSettings(ImmutableModel):
    """Explicit mapping from venue identity to calendar implementation."""

    mic: str
    name: str
    country_code: str
    timezone_name: str
    calendar_name: str | None


class MarketSettings(ImmutableModel):
    """Market and exchange configuration."""

    default_exchange_mic: str = "XNYS"
    exchanges: tuple[ExchangeSettings, ...] = Field(
        default_factory=lambda: (
            ExchangeSettings(
                mic="XNYS",
                name="New York Stock Exchange",
                country_code="US",
                timezone_name="America/New_York",
                calendar_name="XNYS",
            ),
            ExchangeSettings(
                mic="XBOM",
                name="BSE Limited",
                country_code="IN",
                timezone_name="Asia/Kolkata",
                calendar_name="XBOM",
            ),
        )
    )

    @model_validator(mode="after")
    def validate_exchange_set(self) -> Self:
        normalized = [item.mic.strip().upper() for item in self.exchanges]
        if len(set(normalized)) != len(normalized):
            msg = "Configured exchange MICs must be unique"
            raise ValueError(msg)
        if self.default_exchange_mic.strip().upper() not in set(normalized):
            msg = "Default exchange MIC must be present in the configured exchange list"
            raise ValueError(msg)
        return self


class StorageSettings(ImmutableModel):
    """Storage roots for local adapters; cloud adapters are selected in later deployments."""

    data_root: Path = Path(".local/data")
    raw_objects_subdirectory: str = "raw-objects"
    ingestion_catalog_subdirectory: str = "ingestion-catalog"
    experiment_events_subdirectory: str = "experiment-events"

    @model_validator(mode="after")
    def validate_subdirectories(self) -> Self:
        for value in (
            self.raw_objects_subdirectory,
            self.ingestion_catalog_subdirectory,
            self.experiment_events_subdirectory,
        ):
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or not value.strip():
                msg = "Storage subdirectories must be safe relative paths"
                raise ValueError(msg)
        return self


class DatabaseSettings(ImmutableModel):
    """Operational database connectivity; production uses PostgreSQL migrations."""

    url: str = "sqlite+pysqlite:///.local/data/operations.db"
    echo: bool = False
    pool_pre_ping: bool = True

    @model_validator(mode="after")
    def validate_database_url(self) -> Self:
        value = self.url.strip()
        if not value or "://" not in value:
            raise ValueError("Database URL must include a SQLAlchemy scheme")
        object.__setattr__(self, "url", value)
        return self


class ApiSettings(ImmutableModel):
    """Secured internal API runtime settings."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    request_body_limit_bytes: int = Field(default=1_048_576, ge=1024, le=16_777_216)
    rate_limit_requests: int = Field(default=120, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_maximum_clients: int = Field(default=10_000, ge=100, le=1_000_000)
    docs_enabled: bool = True
    jwt_issuer: str = "https://identity.example.invalid/"
    jwt_audience: str = "stock-forecasting-platform"
    jwt_algorithms: tuple[str, ...] = ("RS256",)
    jwt_verification_key: SecretStr | None = None
    jwt_verification_key_path: Path | None = None

    @model_validator(mode="after")
    def validate_api_policy(self) -> Self:
        hosts = tuple(item.strip().lower() for item in self.allowed_hosts)
        algorithms = tuple(item.strip().upper() for item in self.jwt_algorithms)
        if not self.host.strip() or not hosts or any(not item for item in hosts):
            raise ValueError("API host and allowed hosts cannot be blank")
        if len(set(hosts)) != len(hosts) or "*" in hosts:
            raise ValueError("API allowed hosts must be unique and cannot use a wildcard")
        if not self.jwt_issuer.strip() or not self.jwt_audience.strip() or not algorithms:
            raise ValueError("API JWT issuer, audience, and algorithms are required")
        if self.jwt_verification_key is not None and self.jwt_verification_key_path is not None:
            raise ValueError("Configure either an inline JWT key or a JWT key path, not both")
        object.__setattr__(self, "host", self.host.strip())
        object.__setattr__(self, "allowed_hosts", hosts)
        object.__setattr__(self, "jwt_algorithms", algorithms)
        return self


class PaperTradingSettings(ImmutableModel):
    """Paper-only execution costs, freshness, and risk limits."""

    spread_bps: Decimal = Field(default=Decimal("5"), ge=0)
    slippage_bps: Decimal = Field(default=Decimal("2"), ge=0)
    commission_bps: Decimal = Field(default=Decimal("1"), ge=0)
    fixed_commission: Decimal = Field(default=Decimal("0"), ge=0)
    maximum_order_notional: Decimal = Field(default=Decimal("1000000"), gt=0)
    maximum_position_notional: Decimal = Field(default=Decimal("2000000"), gt=0)
    maximum_price_age_seconds: int = Field(default=1800, ge=1, le=86_400)
    idempotency_ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)


class ObservabilitySettings(ImmutableModel):
    """Metrics and trace identity without high-cardinality labels."""

    metrics_namespace: str = "stock_predictor"
    service_name: str = "stock-forecasting-platform"

    @model_validator(mode="after")
    def validate_names(self) -> Self:
        namespace = self.metrics_namespace.strip().lower()
        service = self.service_name.strip()
        if not namespace or not namespace.replace("_", "").isalnum() or not service:
            raise ValueError("Observability namespace or service name is invalid")
        object.__setattr__(self, "metrics_namespace", namespace)
        object.__setattr__(self, "service_name", service)
        return self


class IngestionSettings(ImmutableModel):
    """Bounded market-data ingestion behavior."""

    maximum_pages: int = Field(default=10_000, ge=1, le=1_000_000)
    maximum_page_bytes: int = Field(default=64 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)


class DataQualitySettings(ImmutableModel):
    """Deterministic quality-gate policy."""

    rule_set_version: str = "price-bars-v1"
    minimum_acceptable_score: Decimal = Field(default=Decimal("80"), ge=0, le=100)
    timeliness_warning_seconds: int = Field(default=6 * 60 * 60, ge=0)

    @property
    def timeliness_warning_after(self) -> timedelta:
        return timedelta(seconds=self.timeliness_warning_seconds)


class FeatureEngineeringSettings(ImmutableModel):
    """Default feature-materialization behavior."""

    use_point_in_time_adjustments: bool = True


class ModelingSettings(ImmutableModel):
    """Conservative training, artifact, and paper-backtesting defaults."""

    maximum_hyperparameter_trials: int = Field(default=100, ge=1, le=10_000)
    calibration_bins: int = Field(default=10, ge=2, le=100)
    allow_trusted_model_deserialization: bool = False
    backtesting_only: bool = True


class ModelRegistrySettings(ImmutableModel):
    """Governed model-promotion gates and approvals."""

    required_gate_names: tuple[str, ...] = (
        "artifact_verified",
        "dataset_lineage_verified",
        "baseline_outperformed",
        "backtest_passed",
        "risk_limits_passed",
        "security_checks_passed",
    )
    required_approval_roles: tuple[str, ...] = (
        "model_validator",
        "risk_owner",
        "deployment_approver",
    )

    @model_validator(mode="after")
    def validate_registry_policy(self) -> Self:
        gates = tuple(item.strip().lower() for item in self.required_gate_names)
        roles = tuple(item.strip().lower() for item in self.required_approval_roles)
        if not gates or any(not item for item in gates) or len(set(gates)) != len(gates):
            raise ValueError("Model-registry gates must be unique and non-empty")
        if not roles or any(not item for item in roles) or len(set(roles)) != len(roles):
            raise ValueError(
                "Model-registry approval roles must be unique and non-empty"
            )
        supported_roles = {
            "model_validator",
            "risk_owner",
            "deployment_approver",
        }
        unsupported = sorted(set(roles) - supported_roles)
        if unsupported:
            raise ValueError(
                "Unsupported model-registry approval roles: " + ", ".join(unsupported)
            )
        object.__setattr__(self, "required_gate_names", gates)
        object.__setattr__(self, "required_approval_roles", roles)
        return self


class InferenceSettings(ImmutableModel):
    """Bounded prediction-serving behavior."""

    maximum_batch_size: int = Field(default=10_000, ge=1, le=1_000_000)


class MonitoringSettings(ImmutableModel):
    """Distribution and realized-performance monitoring thresholds."""

    minimum_samples: int = Field(default=30, ge=2)
    histogram_bins: int = Field(default=10, ge=2, le=100)
    psi_warning: Decimal = Field(default=Decimal("0.10"), ge=0)
    psi_critical: Decimal = Field(default=Decimal("0.25"), gt=0)
    mean_shift_warning: Decimal = Field(default=Decimal("0.50"), ge=0)
    mean_shift_critical: Decimal = Field(default=Decimal("1.00"), gt=0)
    missing_delta_warning: Decimal = Field(default=Decimal("0.05"), ge=0)
    missing_delta_critical: Decimal = Field(default=Decimal("0.15"), gt=0)
    js_warning: Decimal = Field(default=Decimal("0.05"), ge=0)
    js_critical: Decimal = Field(default=Decimal("0.15"), gt=0)
    performance_degradation_warning: Decimal = Field(default=Decimal("0.10"), ge=0)
    performance_degradation_critical: Decimal = Field(default=Decimal("0.25"), gt=0)
    directional_accuracy_warning: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    directional_accuracy_critical: Decimal = Field(default=Decimal("0.45"), ge=0, le=1)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> Self:
        ordered = (
            (self.psi_warning, self.psi_critical),
            (self.mean_shift_warning, self.mean_shift_critical),
            (self.missing_delta_warning, self.missing_delta_critical),
            (self.js_warning, self.js_critical),
            (
                self.performance_degradation_warning,
                self.performance_degradation_critical,
            ),
        )
        if any(critical <= warning for warning, critical in ordered):
            raise ValueError("Monitoring critical thresholds must exceed warning thresholds")
        if self.directional_accuracy_critical >= self.directional_accuracy_warning:
            raise ValueError(
                "Critical directional accuracy must be below the warning threshold"
            )
        return self


class ContinuousTrainingSettings(ImmutableModel):
    """Conservative champion-challenger automation policy."""

    minimum_outcomes: int = Field(default=30, ge=1)
    minimum_improvement: Decimal = Field(default=Decimal("0.01"), ge=0)
    allow_automatic_promotion: bool = False


class SecuritySettings(ImmutableModel):
    """Secret-source and sensitive provider settings."""

    secret_backend: SecretBackend = SecretBackend.ENVIRONMENT
    secret_directory: Path | None = None
    market_data_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_secret_backend(self) -> Self:
        if self.secret_backend is SecretBackend.DIRECTORY and self.secret_directory is None:
            msg = "Directory secret backend requires security.secret_directory"
            raise ValueError(msg)
        return self


class FeatureFlagSettings(ImmutableModel):
    """Controlled feature switches; defaults remain conservative."""

    enable_experimental_calendars: bool = False
    enable_future_online_inference: bool = False
    enable_future_live_trading: bool = False


class PlatformSettings(BaseSettings):
    """Root settings object.

    Environment variables use the `SP_` prefix and `__` nested delimiter, for example
    `SP_APP__ENVIRONMENT=production`.
    """

    model_config = SettingsConfigDict(
        env_prefix="SP_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=False,
        frozen=True,
        validate_default=True,
    )

    app: ApplicationSettings = Field(default_factory=ApplicationSettings)
    market: MarketSettings = Field(default_factory=MarketSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    paper_trading: PaperTradingSettings = Field(default_factory=PaperTradingSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    features: FeatureFlagSettings = Field(default_factory=FeatureFlagSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    quality: DataQualitySettings = Field(default_factory=DataQualitySettings)
    feature_engineering: FeatureEngineeringSettings = Field(
        default_factory=FeatureEngineeringSettings
    )
    modeling: ModelingSettings = Field(default_factory=ModelingSettings)
    model_registry: ModelRegistrySettings = Field(default_factory=ModelRegistrySettings)
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    continuous_training: ContinuousTrainingSettings = Field(
        default_factory=ContinuousTrainingSettings
    )

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Self:
        if self.app.environment is RuntimeEnvironment.PRODUCTION and self.app.debug:
            msg = "Debug mode is prohibited in production"
            raise ValueError(msg)
        if not self.modeling.backtesting_only:
            msg = "The platform supports research, inference, and paper evaluation only"
            raise ValueError(msg)
        if (
            self.app.environment is RuntimeEnvironment.PRODUCTION
            and self.features.enable_future_live_trading
        ):
            msg = "Live trading is not implemented or approved and cannot be enabled"
            raise ValueError(msg)
        return self

    def validate_api_runtime(self) -> None:
        """Reject development-only API settings before starting a managed runtime."""
        if not self.api.enabled:
            raise ValueError("API runtime is disabled")
        if (
            self.api.jwt_verification_key is None
            and self.api.jwt_verification_key_path is None
        ):
            raise ValueError("API JWT verification key or key path is required")
        if self.app.environment in {RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION}:
            if self.database.url.startswith("sqlite"):
                raise ValueError("Managed API runtimes require a PostgreSQL database")
            if self.api.docs_enabled:
                raise ValueError(
                    "Interactive API documentation must be disabled in managed runtimes"
                )
            if any(item.startswith("HS") for item in self.api.jwt_algorithms):
                raise ValueError(
                    "Managed API runtimes require asymmetric JWT verification"
                )

    def api_verification_key(self) -> str:
        """Resolve the JWT verification key without exposing it in diagnostics."""
        if self.api.jwt_verification_key is not None:
            return self.api.jwt_verification_key.get_secret_value()
        path = self.api.jwt_verification_key_path
        if path is None:
            raise ValueError("API JWT verification key or key path is required")
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Unable to read API JWT verification key: {path}") from exc
        if not value:
            raise ValueError("API JWT verification key file is empty")
        return value

    def safe_summary(self) -> dict[str, object]:
        """Return non-secret diagnostic settings suitable for logs or CLI output."""
        return {
            "application": self.app.name,
            "environment": self.app.environment.value,
            "debug": self.app.debug,
            "log_level": self.app.log_level.value,
            "data_root": str(self.storage.data_root),
            "database_driver": self.database.url.split(":", 1)[0],
            "api_enabled": self.api.enabled,
            "api_allowed_hosts": list(self.api.allowed_hosts),
            "api_jwt_key_configured": (
                self.api.jwt_verification_key is not None
                or self.api.jwt_verification_key_path is not None
            ),
            "paper_trading_only": True,
            "metrics_namespace": self.observability.metrics_namespace,
            "default_exchange_mic": self.market.default_exchange_mic,
            "configured_exchanges": [item.mic for item in self.market.exchanges],
            "secret_backend": self.security.secret_backend.value,
            "market_data_api_key_configured": self.security.market_data_api_key is not None,
            "live_trading_enabled": self.features.enable_future_live_trading,
            "ingestion_maximum_pages": self.ingestion.maximum_pages,
            "ingestion_maximum_page_bytes": self.ingestion.maximum_page_bytes,
            "quality_rule_set_version": self.quality.rule_set_version,
            "quality_minimum_score": str(self.quality.minimum_acceptable_score),
            "point_in_time_adjustments_enabled": (
                self.feature_engineering.use_point_in_time_adjustments
            ),
            "maximum_hyperparameter_trials": (
                self.modeling.maximum_hyperparameter_trials
            ),
            "trusted_model_deserialization_enabled": (
                self.modeling.allow_trusted_model_deserialization
            ),
            "backtesting_only": self.modeling.backtesting_only,
            "inference_maximum_batch_size": self.inference.maximum_batch_size,
            "online_inference_enabled": self.features.enable_future_online_inference,
            "monitoring_minimum_samples": self.monitoring.minimum_samples,
            "automatic_model_promotion_enabled": (
                self.continuous_training.allow_automatic_promotion
            ),
        }


def load_settings(env_file: str | Path | None = ".env") -> PlatformSettings:
    """Load and validate settings from environment and an optional dotenv file."""
    return PlatformSettings(_env_file=env_file)
