"""Thread-safe optional materialized feature store."""

from __future__ import annotations

from datetime import date
from threading import RLock

from stock_predictor.domain.common.errors import DomainConflictError
from stock_predictor.domain.common.identifiers import FeatureSetVersionId, InstrumentId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.features import FeatureSnapshot


class InMemoryFeatureStore:
    __slots__ = ("_by_key", "_lock")

    def __init__(self) -> None:
        self._by_key: dict[
            tuple[FeatureSetVersionId, InstrumentId, date, UtcInstant, str], FeatureSnapshot
        ] = {}
        self._lock = RLock()

    @staticmethod
    def _key(snapshot: FeatureSnapshot) -> tuple[
        FeatureSetVersionId, InstrumentId, date, UtcInstant, str
    ]:
        return (
            snapshot.feature_set.feature_set_version_id,
            snapshot.instrument_id,
            snapshot.as_of,
            snapshot.decision_cutoff,
            snapshot.input_fingerprint,
        )

    def put(self, snapshot: FeatureSnapshot) -> None:
        key = self._key(snapshot)
        with self._lock:
            existing = self._by_key.get(key)
            if existing is not None and existing != snapshot:
                raise DomainConflictError("Feature snapshot key already exists with different data")
            self._by_key[key] = snapshot

    def get(
        self,
        feature_set_version_id: FeatureSetVersionId,
        instrument_id: InstrumentId,
        as_of: date,
        decision_cutoff: UtcInstant,
        input_fingerprint: str,
    ) -> FeatureSnapshot | None:
        with self._lock:
            return self._by_key.get(
                (
                    feature_set_version_id,
                    instrument_id,
                    as_of,
                    decision_cutoff,
                    input_fingerprint,
                )
            )
