"""Thread-safe append-only point-in-time price-bar and adjustment repositories."""

from __future__ import annotations

from datetime import date
from threading import RLock

from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.contracts import BarFrequency
from stock_predictor.domain.market_data.point_in_time import (
    AdjustmentFactor,
    NormalizedPriceBar,
    PriceBarKey,
)


class InMemoryPriceBarRepository:
    """Maintains all revisions and resolves the latest record available at a cutoff."""

    __slots__ = ("_bar_ids", "_by_key", "_lock")

    def __init__(self) -> None:
        self._by_key: dict[PriceBarKey, list[NormalizedPriceBar]] = {}
        self._bar_ids: dict[str, NormalizedPriceBar] = {}
        self._lock = RLock()

    def append(self, bar: NormalizedPriceBar) -> None:
        with self._lock:
            identifier = str(bar.bar_id)
            existing_id = self._bar_ids.get(identifier)
            if existing_id is not None:
                if existing_id != bar:
                    raise DomainConflictError("Price-bar ID already exists with different data")
                return
            revisions = self._by_key.setdefault(bar.key, [])
            if revisions:
                latest = revisions[-1]
                if bar.provider != latest.provider:
                    raise DomainConflictError("A price-bar history cannot change source provider")
                if bar.provider_revision <= latest.provider_revision:
                    raise DomainConflictError("Provider revision must strictly increase")
                if bar.normalized_at < latest.normalized_at:
                    raise DomainConflictError(
                        "A correction cannot arrive before the prior revision"
                    )
                if bar.supersedes_bar_id != latest.bar_id:
                    raise DomainConflictError("A correction must supersede the latest revision")
            elif bar.supersedes_bar_id is not None:
                raise DomainConflictError("An initial price bar cannot supersede another bar")
            revisions.append(bar)
            self._bar_ids[identifier] = bar

    def latest_revision(self, key: PriceBarKey) -> NormalizedPriceBar | None:
        with self._lock:
            revisions = self._by_key.get(key, [])
            return revisions[-1] if revisions else None

    def history(self, key: PriceBarKey) -> tuple[NormalizedPriceBar, ...]:
        with self._lock:
            return tuple(self._by_key.get(key, ()))

    def as_known_at(
        self, key: PriceBarKey, cutoff: UtcInstant
    ) -> NormalizedPriceBar | None:
        with self._lock:
            eligible = [item for item in self._by_key.get(key, ()) if item.available_by(cutoff)]
            if not eligible:
                return None
            latest = max(eligible, key=lambda item: (item.normalized_at, item.provider_revision))
            return None if latest.is_tombstone else latest

    def query_as_known_at(
        self,
        instrument_id: InstrumentId,
        start: date,
        end: date,
        frequency: BarFrequency,
        cutoff: UtcInstant,
    ) -> tuple[NormalizedPriceBar, ...]:
        if end < start:
            raise ValueError("Price-bar query end cannot be earlier than start")
        with self._lock:
            keys = tuple(
                key
                for key in self._by_key
                if key.instrument_id == instrument_id
                and key.frequency is frequency
                and start <= key.session_date <= end
            )
            result = tuple(
                item
                for key in keys
                if (item := self.as_known_at(key, cutoff)) is not None
            )
        return tuple(sorted(result, key=lambda item: item.key.session_date))


class InMemoryAdjustmentFactorRepository:
    __slots__ = ("_by_key", "_factor_ids", "_lock")

    def __init__(self) -> None:
        self._by_key: dict[tuple[InstrumentId, date], list[AdjustmentFactor]] = {}
        self._factor_ids: set[str] = set()
        self._lock = RLock()

    def append(self, factor: AdjustmentFactor) -> None:
        key = (factor.instrument_id, factor.effective_on)
        identifier = str(factor.factor_id)
        with self._lock:
            if identifier in self._factor_ids:
                raise DomainConflictError("Adjustment-factor ID already exists")
            revisions = self._by_key.setdefault(key, [])
            if revisions:
                latest = revisions[-1]
                if factor.provider != latest.provider:
                    raise DomainConflictError("Adjustment-factor source provider cannot change")
                if factor.revision <= latest.revision:
                    raise DomainConflictError("Adjustment-factor revision must strictly increase")
                if factor.timeline.processed_at < latest.timeline.processed_at:
                    raise DomainConflictError("Adjustment correction cannot precede prior revision")
            revisions.append(factor)
            self._factor_ids.add(identifier)

    def factors_as_known_at(
        self, instrument_id: InstrumentId, cutoff: UtcInstant
    ) -> tuple[AdjustmentFactor, ...]:
        with self._lock:
            result: list[AdjustmentFactor] = []
            for (candidate_id, _), revisions in self._by_key.items():
                if candidate_id != instrument_id:
                    continue
                eligible = [item for item in revisions if item.available_by(cutoff)]
                if eligible:
                    result.append(
                        max(eligible, key=lambda item: (item.timeline.processed_at, item.revision))
                    )
        return tuple(sorted(result, key=lambda item: item.effective_on))
