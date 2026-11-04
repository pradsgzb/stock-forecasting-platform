"""Append-only experiment event storage port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import ExperimentRunId
from stock_predictor.domain.modeling.experiments import ExperimentEvent


@runtime_checkable
class ExperimentTracker(Protocol):
    def append(self, event: ExperimentEvent) -> None:
        ...

    def events(self, run_id: ExperimentRunId) -> tuple[ExperimentEvent, ...]:
        ...
