from datetime import UTC, datetime

import numpy as np
import pytest

from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.adapters.models.baselines import ZeroReturnRegressorPlugin
from stock_predictor.domain.common.errors import ModelContractError
from stock_predictor.domain.common.identifiers import ModelVersionId
from stock_predictor.domain.common.temporal import UtcInstant
from tests.helpers.modeling import signature
from tests.unit.adapters.models.test_baselines import spec


def test_joblib_codec_requires_explicit_trust_for_loading() -> None:
    features = np.zeros((3, 2), dtype=np.float64)
    target = np.zeros(3, dtype=np.float64)
    model = ZeroReturnRegressorPlugin().fit(
        spec("baseline.zero_return"),
        signature(),
        features,
        target,
    )
    artifact = TrustedJoblibArtifactCodec().serialize(
        model,
        ModelVersionId.new(),
        UtcInstant(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    artifact.verify()

    with pytest.raises(ModelContractError, match="disabled"):
        TrustedJoblibArtifactCodec().deserialize(artifact)

    loaded = TrustedJoblibArtifactCodec(allow_deserialization=True).deserialize(artifact)
    assert np.all(loaded.predict(features) == 0)
