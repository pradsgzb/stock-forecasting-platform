"""Application data transfer objects for decoded and validated market data."""

from __future__ import annotations

from dataclasses import dataclass

from stock_predictor.domain.common.errors import DataQualityGateError
from stock_predictor.domain.market_data.contracts import ProviderPriceBar
from stock_predictor.domain.market_data.ingestion import IngestionManifest, Sha256Digest
from stock_predictor.domain.market_data.quality import ValidationReport


@dataclass(frozen=True, slots=True)
class DecodedPriceBar:
    record: ProviderPriceBar
    page_number: int
    record_index: int
    source_digest: Sha256Digest


@dataclass(frozen=True, slots=True)
class ValidatedPriceBarBatch:
    manifest: IngestionManifest
    records: tuple[DecodedPriceBar, ...]
    report: ValidationReport

    def require_accepted(self) -> None:
        if not self.report.accepted:
            raise DataQualityGateError(
                f"Market-data batch failed quality gate: {self.report.status.value}"
            )
