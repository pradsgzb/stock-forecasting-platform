"""Checksummed joblib codec restricted to trusted model artifacts."""

from __future__ import annotations

from io import BytesIO
from typing import cast

import joblib

from stock_predictor.domain.common.errors import ModelContractError
from stock_predictor.domain.common.identifiers import ModelArtifactId, ModelVersionId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.models import ModelArtifact
from stock_predictor.ports.model_plugin import FittedModel

_MEDIA_TYPE = "application/vnd.stock-predictor.trusted-joblib"


class TrustedJoblibArtifactCodec:
    """Serializes Python estimators but refuses deserialization unless explicitly trusted.

    Joblib uses pickle semantics. The checksum prevents accidental corruption, not malicious
    payloads; production callers must fetch artifacts only from an authenticated registry and
    construct this codec with `allow_deserialization=True` inside that trusted boundary.
    """

    __slots__ = ("_allow_deserialization",)

    def __init__(self, *, allow_deserialization: bool = False) -> None:
        self._allow_deserialization = allow_deserialization

    def serialize(
        self,
        model: FittedModel,
        model_version_id: ModelVersionId,
        created_at: UtcInstant,
    ) -> ModelArtifact:
        model.health_check()
        buffer = BytesIO()
        joblib.dump(model, buffer, compress=3)
        return ModelArtifact(
            artifact_id=ModelArtifactId.new(),
            model_version_id=model_version_id,
            spec=model.spec,
            signature=model.signature,
            media_type=_MEDIA_TYPE,
            payload=buffer.getvalue(),
            created_at=created_at,
        )

    def deserialize(self, artifact: ModelArtifact) -> FittedModel:
        artifact.verify()
        if artifact.media_type != _MEDIA_TYPE:
            raise ModelContractError(
                f"Unsupported model artifact media type: {artifact.media_type}"
            )
        if not self._allow_deserialization:
            raise ModelContractError(
                "Trusted joblib deserialization is disabled; enable it only behind a "
                "verified artifact registry"
            )
        # nosec B301: checksum, media type, and an explicit trusted-boundary flag gate loading.
        loaded = joblib.load(BytesIO(artifact.payload))
        required = (
            "spec",
            "signature",
            "predict",
            "predict_positive_probability",
            "native_feature_importance",
            "health_check",
        )
        if any(not hasattr(loaded, name) for name in required):
            raise ModelContractError("Artifact does not contain a fitted-model contract")
        model = cast(FittedModel, loaded)
        if model.spec != artifact.spec or model.signature != artifact.signature:
            raise ModelContractError("Artifact metadata differs from serialized model")
        model.health_check()
        return model
