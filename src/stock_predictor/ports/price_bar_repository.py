"""Ports for point-in-time normalized bars and adjustment factors."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.contracts import BarFrequency
from stock_predictor.domain.market_data.point_in_time import (
    AdjustmentFactor,
    NormalizedPriceBar,
    PriceBarKey,
)


@runtime_checkable
class PriceBarRepository(Protocol):
    """Append-only revision store with explicit point-in-time queries."""

    def append(self, bar: NormalizedPriceBar) -> None:
        ...

    def latest_revision(self, key: PriceBarKey) -> NormalizedPriceBar | None:
        ...

    def history(self, key: PriceBarKey) -> tuple[NormalizedPriceBar, ...]:
        ...

    def as_known_at(
        self, key: PriceBarKey, cutoff: UtcInstant
    ) -> NormalizedPriceBar | None:
        ...

    def query_as_known_at(
        self,
        instrument_id: InstrumentId,
        start: date,
        end: date,
        frequency: BarFrequency,
        cutoff: UtcInstant,
    ) -> tuple[NormalizedPriceBar, ...]:
        ...


@runtime_checkable
class AdjustmentFactorRepository(Protocol):
    """Append-only point-in-time adjustment-factor revisions."""

    def append(self, factor: AdjustmentFactor) -> None:
        ...

    def factors_as_known_at(
        self, instrument_id: InstrumentId, cutoff: UtcInstant
    ) -> tuple[AdjustmentFactor, ...]:
        ...
