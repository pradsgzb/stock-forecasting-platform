"""Strong UUID-backed identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4

from stock_predictor.domain.common.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class UuidId:
    """Base for type-safe UUID identifiers.

    Subclasses are intentionally distinct at runtime so an instrument ID cannot be
    accidentally substituted for a model-version ID.
    """

    value: UUID

    def __post_init__(self) -> None:
        if self.value.int == 0:
            msg = f"{type(self).__name__} cannot use the nil UUID"
            raise DomainValidationError(msg)

    @classmethod
    def new(cls) -> Self:
        """Create a cryptographically random identifier."""
        return cls(uuid4())

    @classmethod
    def parse(cls, raw: str | UUID) -> Self:
        """Parse an identifier from text or a UUID instance."""
        try:
            value = raw if isinstance(raw, UUID) else UUID(raw.strip())
        except (AttributeError, ValueError) as exc:
            msg = f"Invalid {cls.__name__}: {raw!r}"
            raise DomainValidationError(msg) from exc
        return cls(value)

    def __str__(self) -> str:
        return str(self.value)


class InstrumentId(UuidId):
    """Stable internal identity for a financial instrument."""

    __slots__ = ()


class ModelVersionId(UuidId):
    """Identity for a future registered model version."""

    __slots__ = ()


class DatasetVersionId(UuidId):
    """Identity for an immutable dataset snapshot."""

    __slots__ = ()


class FeatureSetVersionId(UuidId):
    """Identity for a versioned feature definition set."""

    __slots__ = ()


class UniverseSnapshotId(UuidId):
    """Identity for an immutable universe snapshot."""

    __slots__ = ()


class IngestionRunId(UuidId):
    """Identity for one resumable market-data ingestion run."""

    __slots__ = ()


class PriceBarId(UuidId):
    """Identity for one immutable normalized price-bar revision."""

    __slots__ = ()


class ValidationReportId(UuidId):
    """Identity for an immutable data-quality validation report."""

    __slots__ = ()


class AdjustmentFactorId(UuidId):
    """Identity for one point-in-time corporate-action adjustment revision."""

    __slots__ = ()


class FeatureSnapshotId(UuidId):
    """Identity for an immutable materialized feature snapshot."""

    __slots__ = ()


class TargetDefinitionId(UuidId):
    """Identity for a versioned prediction target definition."""

    __slots__ = ()


class LabelId(UuidId):
    """Identity for one immutable realized label observation."""

    __slots__ = ()


class DatasetRowId(UuidId):
    """Identity for one immutable row in a dataset snapshot."""

    __slots__ = ()


class ExperimentRunId(UuidId):
    """Identity for one auditable model-development experiment."""

    __slots__ = ()


class ModelArtifactId(UuidId):
    """Identity for one serialized fitted-model artifact."""

    __slots__ = ()


class BacktestRunId(UuidId):
    """Identity for one immutable backtest result."""

    __slots__ = ()


class SignalId(UuidId):
    """Identity for one immutable forecast signal."""

    __slots__ = ()


class OrderId(UuidId):
    """Identity for a simulated order."""

    __slots__ = ()


class FillId(UuidId):
    """Identity for a simulated execution fill."""

    __slots__ = ()


class RegistryTransitionId(UuidId):
    """Identity for one immutable model-registry transition."""

    __slots__ = ()


class ModelDeploymentId(UuidId):
    """Identity for one model deployment record."""

    __slots__ = ()


class PredictionBatchId(UuidId):
    """Identity for one immutable inference batch."""

    __slots__ = ()


class PredictionId(UuidId):
    """Identity for one immutable prediction."""

    __slots__ = ()


class OutcomeId(UuidId):
    """Identity for one immutable realized outcome revision."""

    __slots__ = ()


class DriftReportId(UuidId):
    """Identity for one immutable drift report."""

    __slots__ = ()


class MonitoringSnapshotId(UuidId):
    """Identity for one immutable performance-monitoring snapshot."""

    __slots__ = ()


class MonitoringAlertId(UuidId):
    """Identity for one immutable monitoring alert."""

    __slots__ = ()


class RetrainingRequestId(UuidId):
    """Identity for one controlled retraining request."""

    __slots__ = ()

class AuditEventId(UuidId):
    """Identity for one tamper-evident operational audit event."""

    __slots__ = ()


class OutboxEventId(UuidId):
    """Identity for one transactional outbox event."""

    __slots__ = ()


class PaperAccountId(UuidId):
    """Identity for one isolated paper-trading account."""

    __slots__ = ()


class PaperOrderId(UuidId):
    """Identity for one paper order."""

    __slots__ = ()


class PaperFillId(UuidId):
    """Identity for one paper execution fill."""

    __slots__ = ()


class SloSnapshotId(UuidId):
    """Identity for one immutable service-level measurement."""

    __slots__ = ()
