"""Thread-safe immutable validation-report repository."""

from __future__ import annotations

from threading import RLock

from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.common.identifiers import IngestionRunId
from stock_predictor.domain.market_data.quality import ValidationReport


class InMemoryValidationReportRepository:
    __slots__ = ("_by_id", "_by_run", "_lock")

    def __init__(self) -> None:
        self._by_id: dict[str, ValidationReport] = {}
        self._by_run: dict[IngestionRunId, list[ValidationReport]] = {}
        self._lock = RLock()

    def add(self, report: ValidationReport) -> None:
        key = str(report.report_id)
        with self._lock:
            existing = self._by_id.get(key)
            if existing is not None and existing != report:
                raise DomainConflictError("Validation report ID already exists")
            if existing is not None:
                return
            self._by_id[key] = report
            self._by_run.setdefault(report.ingestion_run_id, []).append(report)

    def latest_for_run(self, run_id: IngestionRunId) -> ValidationReport | None:
        with self._lock:
            reports = self._by_run.get(run_id, [])
            return max(reports, key=lambda item: item.generated_at) if reports else None
