from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import ExperimentRunId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.evaluation import MetricDirection
from stock_predictor.domain.modeling.experiments import (
    ExperimentEvent,
    ExperimentEventType,
)
from stock_predictor.domain.modeling.training import TrialStatus, TrialSummary
from tests.unit.domain.modeling.test_models_and_evaluation import make_spec


def test_experiment_event_canonicalizes_json_and_fingerprints() -> None:
    run_id = ExperimentRunId.new()
    instant = UtcInstant(datetime(2026, 1, 1, tzinfo=UTC))
    first = ExperimentEvent.create(
        run_id,
        1,
        ExperimentEventType.STARTED,
        instant,
        {"z": 1, "a": "value"},
    )
    second = ExperimentEvent(
        run_id,
        1,
        ExperimentEventType.STARTED,
        instant,
        '{"a":"value","z":1}',
    )
    assert first.fingerprint == second.fingerprint
    assert first.details == {"a": "value", "z": 1}

    with pytest.raises(DomainValidationError, match="positive"):
        ExperimentEvent(run_id, 0, ExperimentEventType.STARTED, instant, "{}")
    with pytest.raises(DomainValidationError, match="must be JSON"):
        ExperimentEvent(run_id, 1, ExperimentEventType.STARTED, instant, "{")
    with pytest.raises(DomainValidationError, match="JSON object"):
        ExperimentEvent(run_id, 1, ExperimentEventType.STARTED, instant, "[]")


def test_trial_summary_enforces_status_specific_evidence() -> None:
    spec = make_spec()
    completed = TrialSummary(
        1,
        spec,
        TrialStatus.COMPLETED,
        (Decimal("0.1"), Decimal("0.2")),
        Decimal("0.15"),
        "mae",
        MetricDirection.MINIMIZE,
    )
    failed = TrialSummary(
        2,
        spec,
        TrialStatus.FAILED,
        (),
        None,
        "mae",
        MetricDirection.MINIMIZE,
        "training failed",
    )
    assert completed.mean_score == Decimal("0.15")
    assert failed.failure_reason == "training failed"

    with pytest.raises(DomainValidationError, match="Completed"):
        TrialSummary(
            1,
            spec,
            TrialStatus.COMPLETED,
            (),
            None,
            "mae",
            MetricDirection.MINIMIZE,
        )
    with pytest.raises(DomainValidationError, match="Failed"):
        TrialSummary(
            1,
            spec,
            TrialStatus.FAILED,
            (Decimal("1"),),
            Decimal("1"),
            "mae",
            MetricDirection.MINIMIZE,
            "failed",
        )
