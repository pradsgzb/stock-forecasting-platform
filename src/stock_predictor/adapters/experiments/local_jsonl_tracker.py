"""Durable local append-only JSONL experiment event tracker."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.common.identifiers import ExperimentRunId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.modeling.experiments import (
    ExperimentEvent,
    ExperimentEventType,
)


class LocalJsonlExperimentTracker:
    __slots__ = ("_lock", "_root")

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, run_id: ExperimentRunId) -> Path:
        return self._root / f"{run_id}.jsonl"

    def append(self, event: ExperimentEvent) -> None:
        with self._lock:
            existing = self.events(event.run_id)
            same_sequence = next(
                (item for item in existing if item.sequence == event.sequence),
                None,
            )
            if same_sequence is not None:
                if same_sequence.fingerprint == event.fingerprint:
                    return
                raise DomainConflictError(
                    f"Experiment sequence already contains different evidence: "
                    f"{event.run_id}/{event.sequence}"
                )
            expected = len(existing) + 1
            if event.sequence != expected:
                raise DomainConflictError(
                    f"Experiment sequence must be contiguous; expected {expected}, "
                    f"received {event.sequence}"
                )
            record = {
                "run_id": str(event.run_id),
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "occurred_at": event.occurred_at.isoformat(),
                "details_json": event.details_json,
                "fingerprint": event.fingerprint,
            }
            line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            path = self._path(event.run_id)
            descriptor = os.open(
                path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(descriptor, line.encode("utf-8"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def events(self, run_id: ExperimentRunId) -> tuple[ExperimentEvent, ...]:
        path = self._path(run_id)
        if not path.exists():
            return ()
        result: list[ExperimentEvent] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                raw = json.loads(line)
                event = ExperimentEvent(
                    run_id=ExperimentRunId.parse(raw["run_id"]),
                    sequence=int(raw["sequence"]),
                    event_type=ExperimentEventType(raw["event_type"]),
                    occurred_at=UtcInstant.parse(raw["occurred_at"]),
                    details_json=str(raw["details_json"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise DomainConflictError(
                    f"Invalid experiment event at {path}:{line_number}"
                ) from exc
            if event.fingerprint != raw.get("fingerprint"):
                raise DomainConflictError(
                    f"Experiment event checksum mismatch at {path}:{line_number}"
                )
            result.append(event)
        if tuple(item.sequence for item in result) != tuple(range(1, len(result) + 1)):
            raise DomainConflictError(f"Experiment event sequence is broken: {path}")
        return tuple(result)
