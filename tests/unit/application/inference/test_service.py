from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.adapters.repositories.in_memory_model_registry import (
    InMemoryModelRegistryRepository,
)
from stock_predictor.adapters.repositories.in_memory_prediction_ledger import (
    InMemoryPredictionLedger,
)
from stock_predictor.application.inference.service import (
    BatchInferenceRequest,
    ModelInferenceService,
)
from stock_predictor.application.registry.service import ModelRegistryService
from stock_predictor.domain.common.errors import (
    DomainConflictError,
    DomainValidationError,
    InferenceError,
)
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.mlops.inference import PredictionBatchStatus
from stock_predictor.domain.mlops.registry import ModelDeploymentScope
from stock_predictor.domain.modeling.models import LearningTask
from stock_predictor.domain.mlops.registry import ApprovalRole, PromotionPolicy
from stock_predictor.domain.market_data.features import FeatureDefinition, FeatureSet
from stock_predictor.domain.common.identifiers import FeatureSetVersionId
from tests.helpers.mlops import (
    DEFAULT_GATES,
    StubFeaturePipeline,
    feature_set,
    fixed_clock,
    promotion_evidence,
    scope,
    training_result,
)
from tests.helpers.modeling import regression_target


def _champion(fixed_instant, target, features):
    repository = InMemoryModelRegistryRepository()
    registry = ModelRegistryService(
        repository,
        fixed_clock(fixed_instant),
        PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole)),
    )
    result = training_result(fixed_instant, target=target, features=features)
    model_scope = scope(target)
    candidate = registry.register_candidate(result, model_scope, actor="trainer")
    validated, _ = registry.validate_candidate(
        candidate.model_version_id,
        promotion_evidence(fixed_instant),
        actor="validator",
    )
    registry.stage(validated.model_version_id, actor="operator")
    registry.deploy_challenger(
        validated.model_version_id,
        actor="operator",
        reason="shadow",
    )
    registry.promote_challenger(
        validated.model_version_id,
        promotion_evidence(fixed_instant),
        actor="approver",
        reason="promote",
    )
    return repository, result, model_scope


def _request(fixed_instant, target, features, instruments, key="inference-key", **kwargs):
    return BatchInferenceRequest(
        scope(target),
        target,
        features,
        instruments,
        date(2026, 1, 2),
        fixed_instant,
        key,
        **kwargs,
    )


def test_batch_inference_records_lineage_and_is_idempotent(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    repository, result, _ = _champion(fixed_instant, target, features)
    instruments = (InstrumentId.new(), InstrumentId.new())
    pipeline = StubFeaturePipeline(
        features,
        fixed_instant,
        {instruments[0]: Decimal("100"), instruments[1]: Decimal("110")},
    )
    ledger = InMemoryPredictionLedger()
    service = ModelInferenceService(
        repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        pipeline,
        ledger,
        fixed_clock(fixed_instant),
    )
    request = _request(fixed_instant, target, features, instruments)
    batch = service.predict_batch(request)
    repeated = service.predict_batch(request)
    assert batch == repeated
    assert batch.status is PredictionBatchStatus.COMPLETED
    assert len(batch.predictions) == 2
    assert {item.model_version_id for item in batch.predictions} == {
        result.model_version_id
    }
    assert all(item.predicted_value == 0 for item in batch.predictions)
    assert all(item.cross_sectional_rank.value == Decimal("0.5") for item in batch.predictions)


def test_batch_inference_collects_partial_failures(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    repository, _, _ = _champion(fixed_instant, target, features)
    good, bad = InstrumentId.new(), InstrumentId.new()
    service = ModelInferenceService(
        repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        StubFeaturePipeline(features, fixed_instant, failures={bad}),
        InMemoryPredictionLedger(),
        fixed_clock(fixed_instant),
    )
    batch = service.predict_batch(
        _request(
            fixed_instant,
            target,
            features,
            (good, bad),
            fail_fast=False,
        )
    )
    assert batch.status is PredictionBatchStatus.PARTIAL
    assert len(batch.predictions) == 1
    assert batch.failures[0].instrument_id == bad


def test_batch_inference_fail_fast_and_maximum_size(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    repository, _, _ = _champion(fixed_instant, target, features)
    bad = InstrumentId.new()
    service = ModelInferenceService(
        repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        StubFeaturePipeline(features, fixed_instant, failures={bad}),
        InMemoryPredictionLedger(),
        fixed_clock(fixed_instant),
        maximum_batch_size=1,
    )
    with pytest.raises(InferenceError, match="Feature materialization"):
        service.predict_batch(_request(fixed_instant, target, features, (bad,)))
    with pytest.raises(InferenceError, match="maximum"):
        service.predict_batch(
            _request(
                fixed_instant,
                target,
                features,
                (InstrumentId.new(), InstrumentId.new()),
                key="too-large",
            )
        )


def test_inference_requires_champion_and_matching_signature(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    empty_repository = InMemoryModelRegistryRepository()
    service = ModelInferenceService(
        empty_repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        StubFeaturePipeline(features, fixed_instant),
        InMemoryPredictionLedger(),
        fixed_clock(fixed_instant),
    )
    with pytest.raises(InferenceError, match="champion"):
        service.predict_batch(
            _request(fixed_instant, target, features, (InstrumentId.new(),))
        )

    repository, _, _ = _champion(fixed_instant, target, features)
    different_features = FeatureSet(
        FeatureSetVersionId.new(),
        "different",
        "1.0.0",
        (FeatureDefinition("momentum", "1.0.0", "Different feature", 0, 1),),
    )
    mismatch = ModelInferenceService(
        repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        StubFeaturePipeline(different_features, fixed_instant),
        InMemoryPredictionLedger(),
        fixed_clock(fixed_instant),
    )
    with pytest.raises(InferenceError, match="feature signature"):
        mismatch.predict_batch(
            _request(
                fixed_instant,
                target,
                different_features,
                (InstrumentId.new(),),
                key="mismatch",
            )
        )


def test_inference_idempotency_conflict_and_online_policy(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    repository, _, _ = _champion(fixed_instant, target, features)
    instrument = InstrumentId.new()
    ledger = InMemoryPredictionLedger()
    disabled = ModelInferenceService(
        repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        StubFeaturePipeline(features, fixed_instant),
        ledger,
        fixed_clock(fixed_instant),
    )
    first = _request(fixed_instant, target, features, (instrument,))
    disabled.predict_batch(first)
    conflict = _request(
        fixed_instant,
        target,
        features,
        (InstrumentId.new(),),
        key=first.idempotency_key,
    )
    with pytest.raises(DomainConflictError):
        disabled.predict_batch(conflict)
    with pytest.raises(InferenceError, match="disabled"):
        disabled.predict_one(first)

    enabled = ModelInferenceService(
        repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        StubFeaturePipeline(features, fixed_instant),
        InMemoryPredictionLedger(),
        fixed_clock(fixed_instant),
        allow_online=True,
    )
    prediction = enabled.predict_one(
        _request(
            fixed_instant,
            target,
            features,
            (instrument,),
            key="online",
        )
    )
    assert prediction.instrument_id == instrument
    with pytest.raises(InferenceError, match="exactly one"):
        enabled.predict_one(
            _request(
                fixed_instant,
                target,
                features,
                (instrument, InstrumentId.new()),
                key="bad-online",
            )
        )


def test_inference_request_validation(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    instrument = InstrumentId.new()
    with pytest.raises(DomainValidationError, match="unique"):
        _request(fixed_instant, target, features, (instrument, instrument))
    with pytest.raises(DomainValidationError, match="target"):
        BatchInferenceRequest(
            ModelDeploymentScope(
                "staging", "different_target@1.0.0", LearningTask.REGRESSION
            ),
            target,
            features,
            (instrument,),
            date(2026, 1, 2),
            fixed_instant,
            "wrong-scope",
        )


def test_inference_rejects_invalid_model_output(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    repository, result, _ = _champion(fixed_instant, target, features)

    class BadModel:
        spec = result.artifact.spec
        signature = result.artifact.signature

        def predict(self, matrix):
            return np.asarray([np.nan] * len(matrix), dtype=np.float64)

        def predict_positive_probability(self, matrix):
            return None

        def native_feature_importance(self):
            return None

        def health_check(self):
            return None

    class BadCodec:
        def serialize(self, model, model_version_id, created_at):
            raise AssertionError

        def deserialize(self, artifact):
            return BadModel()

    service = ModelInferenceService(
        repository,
        BadCodec(),
        StubFeaturePipeline(features, fixed_instant),
        InMemoryPredictionLedger(),
        fixed_clock(fixed_instant),
    )
    with pytest.raises(InferenceError, match="non-finite"):
        service.predict_batch(
            _request(
                fixed_instant,
                target,
                features,
                (InstrumentId.new(),),
                key="bad-output",
            )
        )
