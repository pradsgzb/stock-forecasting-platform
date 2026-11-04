"""Domain-specific exceptions.

Exceptions communicate failed business invariants without exposing infrastructure details.
"""


class DomainError(ValueError):
    """Base exception for invalid domain operations or values."""


class DomainValidationError(DomainError):
    """Raised when a value violates a domain invariant."""


class DomainConflictError(DomainError):
    """Raised when otherwise valid state conflicts with existing state."""


class DomainNotFoundError(DomainError):
    """Raised when a requested domain object does not exist."""


class CurrencyMismatchError(DomainValidationError):
    """Raised when arithmetic mixes different currencies."""


class OverlappingEffectivePeriodError(DomainConflictError):
    """Raised when effective-dated records overlap illegally."""


class NonTradingDayError(DomainNotFoundError):
    """Raised when a date is not a session for an exchange."""


class UnsupportedExchangeError(DomainNotFoundError):
    """Raised when no configured calendar exists for an exchange."""


class ProviderContractError(DomainError):
    """Raised when a provider violates its declared market-data contract."""


class ImmutableObjectConflictError(DomainConflictError):
    """Raised when immutable content conflicts with an existing stored object."""


class DataQualityGateError(DomainValidationError):
    """Raised when a batch cannot proceed beyond the configured quality gate."""


class PointInTimeViolationError(DomainValidationError):
    """Raised when data unavailable at a decision cutoff is requested or consumed."""


class FeatureComputationError(DomainValidationError):
    """Raised when a feature cannot be computed under its declared contract."""


class LabelComputationError(DomainValidationError):
    """Raised when a target label cannot be produced under its declared contract."""


class DatasetConstructionError(DomainValidationError):
    """Raised when an immutable dataset cannot be built safely."""


class DatasetSplitError(DomainValidationError):
    """Raised when a time-series split is invalid or would leak information."""


class ModelContractError(DomainValidationError):
    """Raised when model inputs, outputs, or artifacts violate their signature."""


class TrainingPipelineError(DomainError):
    """Raised when an experiment cannot complete under its training policy."""


class EvaluationError(DomainValidationError):
    """Raised when an evaluation request is undefined or internally inconsistent."""


class BacktestError(DomainValidationError):
    """Raised when a backtest violates simulation, accounting, or timing rules."""


class ModelRegistryError(DomainError):
    """Raised when a governed model-lifecycle operation cannot be completed."""


class InferenceError(DomainError):
    """Raised when a prediction request violates serving or lineage controls."""


class FeedbackError(DomainError):
    """Raised when realized outcomes or feedback evidence cannot be produced."""


class MonitoringError(DomainError):
    """Raised when monitoring evidence is invalid or cannot be calculated."""


class ContinuousTrainingError(DomainError):
    """Raised when a governed retraining or promotion workflow fails."""


class PersistenceError(DomainError):
    """Raised when durable operational state cannot be read or committed safely."""


class IdempotencyConflictError(DomainConflictError):
    """Raised when an idempotency key is reused for a different request."""


class AuthenticationError(DomainError):
    """Raised when caller identity cannot be established."""


class AuthorizationError(DomainError):
    """Raised when an authenticated caller lacks a required permission."""


class PaperTradingError(DomainError):
    """Raised when a paper-only portfolio operation violates accounting or risk rules."""


class ObservabilityError(DomainError):
    """Raised when health or service-level evidence is invalid."""
