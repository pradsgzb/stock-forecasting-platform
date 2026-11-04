from datetime import UTC, datetime

import pytest

from stock_predictor.adapters.experiments.in_memory_tracker import (
    InMemoryExperimentTracker,
)
from stock_predictor.adapters.experiments.local_jsonl_tracker import (
    LocalJsonlExperimentTracker,
)
from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.common.identifiers import ExperimentRunId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.experiments import (
    ExperimentEvent,
    ExperimentEventType,
)


def event(run_id, sequence, value="x"):
    return ExperimentEvent.create(
        run_id,
        sequence,
        ExperimentEventType.STARTED if sequence == 1 else ExperimentEventType.COMPLETED,
        UtcInstant(datetime(2026, 1, sequence, tzinfo=UTC)),
        {"value": value},
    )


@pytest.mark.parametrize("factory", [InMemoryExperimentTracker])
def test_in_memory_tracker_is_append_only_and_idempotent(factory) -> None:
    tracker = factory()
    run_id = ExperimentRunId.new()
    first = event(run_id, 1)
    tracker.append(first)
    tracker.append(first)
    tracker.append(event(run_id, 2))

    assert tracker.events(run_id) == (first, event(run_id, 2))
    assert tracker.events(ExperimentRunId.new()) == ()

    with pytest.raises(DomainConflictError, match="different evidence"):
        tracker.append(event(run_id, 1, "different"))
    with pytest.raises(DomainConflictError, match="contiguous"):
        tracker.append(event(run_id, 4))


def test_local_tracker_persists_and_detects_tampering(tmp_path) -> None:
    run_id = ExperimentRunId.new()
    tracker = LocalJsonlExperimentTracker(tmp_path)
    first = event(run_id, 1)
    second = event(run_id, 2)
    tracker.append(first)
    tracker.append(first)
    tracker.append(second)

    reloaded = LocalJsonlExperimentTracker(tmp_path)
    assert reloaded.events(run_id) == (first, second)

    path = tmp_path / f"{run_id}.jsonl"
    text = path.read_text()
    path.write_text(text.replace(first.fingerprint, "0" * 64, 1))
    with pytest.raises(DomainConflictError, match="checksum mismatch"):
        reloaded.events(run_id)
