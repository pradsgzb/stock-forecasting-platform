"""Model contracts, signatures, specifications, artifacts, and model cards."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import ModelArtifactId, ModelVersionId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.common.values import DecimalInput, to_decimal

_MODEL_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
HyperParameterValue: TypeAlias = str | int | bool | Decimal


class LearningTask(StrEnum):
    REGRESSION = "regression"
    BINARY_CLASSIFICATION = "binary_classification"


class ModelFamily(StrEnum):
    BASELINE = "baseline"
    LINEAR = "linear"
    TREE_ENSEMBLE = "tree_ensemble"
    CUSTOM = "custom"


def normalize_hyperparameter(value: object, *, name: str) -> HyperParameterValue:
    """Accept deterministic JSON-like hyperparameters while prohibiting binary floats."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise DomainValidationError(f"Hyperparameter {name!r} cannot be blank")
        return normalized
    if isinstance(value, float):
        raise DomainValidationError(
            f"Hyperparameter {name!r} must use Decimal rather than float"
        )
    raise DomainValidationError(
        f"Unsupported hyperparameter type for {name!r}: {type(value).__name__}"
    )


def _json_value(value: HyperParameterValue) -> str | int | bool:
    if isinstance(value, Decimal):
        return str(value)
    return value


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Versioned model-plugin request with canonical hyperparameters."""

    name: str
    version: str
    family: ModelFamily
    task: LearningTask
    plugin_key: str
    random_seed: int
    hyperparameters: tuple[tuple[str, HyperParameterValue], ...] = ()
    fingerprint: str = field(init=False)

    def __init__(
        self,
        name: str,
        version: str,
        family: ModelFamily,
        task: LearningTask,
        plugin_key: str,
        random_seed: int,
        hyperparameters: tuple[tuple[str, object], ...] = (),
    ) -> None:
        normalized_name = name.strip().lower()
        normalized_version = version.strip()
        normalized_plugin = plugin_key.strip().lower()
        if not _MODEL_NAME.fullmatch(normalized_name):
            raise DomainValidationError(f"Invalid model name: {name!r}")
        if not normalized_version or not normalized_plugin:
            raise DomainValidationError("Model version and plugin key are required")
        if random_seed < 0:
            raise DomainValidationError("Model random seed cannot be negative")
        normalized_parameters = tuple(
            sorted(
                (
                    key.strip(),
                    normalize_hyperparameter(value, name=key.strip()),
                )
                for key, value in hyperparameters
            )
        )
        if any(not key for key, _ in normalized_parameters):
            raise DomainValidationError("Hyperparameter names cannot be blank")
        if len({key for key, _ in normalized_parameters}) != len(normalized_parameters):
            raise DomainValidationError("Hyperparameter names must be unique")
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "version", normalized_version)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "plugin_key", normalized_plugin)
        object.__setattr__(self, "random_seed", random_seed)
        object.__setattr__(self, "hyperparameters", normalized_parameters)
        payload = {
            "name": normalized_name,
            "version": normalized_version,
            "family": family.value,
            "task": task.value,
            "plugin_key": normalized_plugin,
            "random_seed": random_seed,
            "hyperparameters": {
                key: _json_value(value) for key, value in normalized_parameters
            },
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    def parameter(self, name: str) -> HyperParameterValue | None:
        normalized = name.strip()
        return next(
            (value for key, value in self.hyperparameters if key == normalized),
            None,
        )

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class ModelSignature:
    """Strict train/serve input and output schema."""

    feature_keys: tuple[str, ...]
    target_key: str
    task: LearningTask

    def __post_init__(self) -> None:
        if not self.feature_keys or len(set(self.feature_keys)) != len(self.feature_keys):
            raise DomainValidationError("Model signature requires unique feature keys")
        if any(not item.strip() for item in self.feature_keys):
            raise DomainValidationError("Model feature keys cannot be blank")
        if not self.target_key.strip():
            raise DomainValidationError("Model target key is required")

    @property
    def fingerprint(self) -> str:
        payload = "|".join((*self.feature_keys, self.target_key, self.task.value)).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    """Checksummed serialized fitted-model artifact from a trusted training pipeline."""

    artifact_id: ModelArtifactId
    model_version_id: ModelVersionId
    spec: ModelSpec
    signature: ModelSignature
    media_type: str
    payload: bytes
    created_at: UtcInstant
    payload_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        media_type = self.media_type.strip().lower()
        if not media_type or not self.payload:
            raise DomainValidationError("Model artifact requires media type and payload")
        if self.spec.task is not self.signature.task:
            raise DomainValidationError("Model spec and signature tasks must match")
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "payload_sha256", hashlib.sha256(self.payload).hexdigest())

    def verify(self) -> None:
        digest = hashlib.sha256(self.payload).hexdigest()
        if digest != self.payload_sha256 or not _SHA256.fullmatch(digest):
            raise DomainValidationError("Model artifact checksum verification failed")


@dataclass(frozen=True, slots=True)
class ModelCard:
    """Human-reviewable summary of intended use, evidence, and limitations."""

    model_version_id: ModelVersionId
    model_key: str
    task: LearningTask
    intended_use: str
    prohibited_uses: tuple[str, ...]
    training_dataset_fingerprint: str
    split_plan_fingerprint: str
    primary_metric: str
    cross_validation_score: Decimal
    holdout_score: Decimal
    limitations: tuple[str, ...]
    generated_at: UtcInstant

    def __post_init__(self) -> None:
        if not self.model_key.strip() or not self.intended_use.strip():
            raise DomainValidationError("Model card identity and intended use are required")
        if not self.prohibited_uses or not self.limitations:
            raise DomainValidationError(
                "Model card must state prohibited uses and known limitations"
            )
        if not self.training_dataset_fingerprint or not self.split_plan_fingerprint:
            raise DomainValidationError("Model card requires dataset and split lineage")
        if not self.primary_metric.strip():
            raise DomainValidationError("Model card primary metric is required")

    @classmethod
    def create(
        cls,
        *,
        model_version_id: ModelVersionId,
        spec: ModelSpec,
        intended_use: str,
        prohibited_uses: tuple[str, ...],
        training_dataset_fingerprint: str,
        split_plan_fingerprint: str,
        primary_metric: str,
        cross_validation_score: DecimalInput,
        holdout_score: DecimalInput,
        limitations: tuple[str, ...],
        generated_at: UtcInstant,
    ) -> ModelCard:
        return cls(
            model_version_id=model_version_id,
            model_key=spec.key,
            task=spec.task,
            intended_use=intended_use,
            prohibited_uses=prohibited_uses,
            training_dataset_fingerprint=training_dataset_fingerprint,
            split_plan_fingerprint=split_plan_fingerprint,
            primary_metric=primary_metric,
            cross_validation_score=to_decimal(
                cross_validation_score, field_name="cross-validation score"
            ),
            holdout_score=to_decimal(holdout_score, field_name="holdout score"),
            limitations=limitations,
            generated_at=generated_at,
        )
