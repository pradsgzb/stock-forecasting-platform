"""Port for immutable market-data validation reports."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import IngestionRunId
from stock_predictor.domain.market_data.quality import ValidationReport


@runtime_checkable
class ValidationReportRepository(Protocol):
    def add(self, report: ValidationReport) -> None:
        ...

    def latest_for_run(self, run_id: IngestionRunId) -> ValidationReport | None:
        ...
