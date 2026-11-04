"""Port for optional materialized feature storage."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import FeatureSetVersionId, InstrumentId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.features import FeatureSnapshot


@runtime_checkable
class FeatureStore(Protocol):
    def put(self, snapshot: FeatureSnapshot) -> None:
        ...

    def get(
        self,
        feature_set_version_id: FeatureSetVersionId,
        instrument_id: InstrumentId,
        as_of: date,
        decision_cutoff: UtcInstant,
        input_fingerprint: str,
    ) -> FeatureSnapshot | None:
        ...
