"""Ports for model plugins, fitted estimators, and trusted artifact codecs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from stock_predictor.domain.common.identifiers import ModelVersionId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelArtifact,
    ModelSignature,
    ModelSpec,
)

FloatMatrix = NDArray[np.float64]
FloatVector = NDArray[np.float64]


@runtime_checkable
class FittedModel(Protocol):
    @property
    def spec(self) -> ModelSpec:
        ...

    @property
    def signature(self) -> ModelSignature:
        ...

    def predict(self, features: FloatMatrix) -> FloatVector:
        ...

    def predict_positive_probability(self, features: FloatMatrix) -> FloatVector | None:
        ...

    def native_feature_importance(self) -> FloatVector | None:
        ...

    def health_check(self) -> None:
        ...


@runtime_checkable
class ModelPlugin(Protocol):
    @property
    def key(self) -> str:
        ...

    @property
    def supported_tasks(self) -> tuple[LearningTask, ...]:
        ...

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        ...


@runtime_checkable
class ModelArtifactCodec(Protocol):
    def serialize(
        self,
        model: FittedModel,
        model_version_id: ModelVersionId,
        created_at: UtcInstant,
    ) -> ModelArtifact:
        ...

    def deserialize(self, artifact: ModelArtifact) -> FittedModel:
        ...
