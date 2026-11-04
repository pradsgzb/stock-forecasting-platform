from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import ContinuousTrainingError, DomainValidationError
from stock_predictor.domain.common.identifiers import ModelVersionId, RetrainingRequestId
from stock_predictor.domain.mlops.continuous_training import (
    ChampionChallengerComparison,
    RetrainingRequest,
    RetrainingStatus,
    RetrainingTrigger,
)
from stock_predictor.domain.modeling.evaluation import MetricDirection
from tests.helpers.mlops import scope


def _request(fixed_instant) -> RetrainingRequest:
    return RetrainingRequest(
        RetrainingRequestId.new(),
        "retrain-key",
        scope(),
        RetrainingTrigger.MANUAL,
        ("ticket:1",),
        "operator",
        fixed_instant,
        RetrainingStatus.PENDING,
        1,
        fixed_instant,
    )


def test_retraining_request_transitions_to_success(fixed_instant) -> None:
    request = _request(fixed_instant)
    running = request.transition(RetrainingStatus.RUNNING, fixed_instant)
    model_id = ModelVersionId.new()
    succeeded = running.transition(
        RetrainingStatus.SUCCEEDED,
        fixed_instant.plus(timedelta(seconds=1)),
        result_model_version_id=model_id,
    )
    assert succeeded.result_model_version_id == model_id
    assert succeeded.revision == 3


def test_retraining_request_rejects_illegal_transition(fixed_instant) -> None:
    request = _request(fixed_instant)
    with pytest.raises(ContinuousTrainingError):
        request.transition(RetrainingStatus.SUCCEEDED, fixed_instant)
    with pytest.raises(DomainValidationError, match="failure reason"):
        RetrainingRequest(
            RetrainingRequestId.new(),
            "key",
            scope(),
            RetrainingTrigger.MANUAL,
            (),
            "actor",
            fixed_instant,
            RetrainingStatus.FAILED,
            2,
            fixed_instant,
        )


def test_comparison_accepts_sufficient_improvement(fixed_instant) -> None:
    comparison = ChampionChallengerComparison(
        champion_model_version_id=ModelVersionId.new(),
        challenger_model_version_id=ModelVersionId.new(),
        metric_name="mae",
        direction=MetricDirection.MINIMIZE,
        champion_value="0.10",
        challenger_value="0.08",
        minimum_improvement="0.01",
        champion_sample_count=50,
        challenger_sample_count=50,
        minimum_sample_count=30,
        compared_at=fixed_instant,
    )
    assert comparison.accepted
    assert comparison.improvement == Decimal("0.02")


def test_comparison_rejects_insufficient_samples_or_gain(fixed_instant) -> None:
    comparison = ChampionChallengerComparison(
        champion_model_version_id=ModelVersionId.new(),
        challenger_model_version_id=ModelVersionId.new(),
        metric_name="directional_accuracy",
        direction=MetricDirection.MAXIMIZE,
        champion_value="0.60",
        challenger_value="0.61",
        minimum_improvement="0.02",
        champion_sample_count=10,
        challenger_sample_count=10,
        minimum_sample_count=30,
        compared_at=fixed_instant,
    )
    assert not comparison.accepted
    assert comparison.improvement == Decimal("0.01")
