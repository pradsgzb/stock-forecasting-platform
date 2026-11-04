"""Immutable point-in-time instrument universes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import InstrumentId, UniverseSnapshotId
from stock_predictor.domain.common.temporal import UtcInstant


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    """Immutable set of instruments eligible under one methodology at an as-of date."""

    snapshot_id: UniverseSnapshotId
    name: str
    as_of: date
    instrument_ids: frozenset[InstrumentId]
    methodology_version: str
    created_at: UtcInstant
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_methodology = self.methodology_version.strip()
        if not normalized_name:
            msg = "Universe name cannot be empty"
            raise DomainValidationError(msg)
        if not normalized_methodology:
            msg = "Universe methodology version cannot be empty"
            raise DomainValidationError(msg)
        if not self.instrument_ids:
            msg = "Universe snapshot cannot be empty"
            raise DomainValidationError(msg)
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "methodology_version", normalized_methodology)
        payload = {
            "name": normalized_name,
            "as_of": self.as_of.isoformat(),
            "methodology_version": normalized_methodology,
            "instrument_ids": sorted(str(item) for item in self.instrument_ids),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical.encode()).hexdigest())

    def contains(self, instrument_id: InstrumentId) -> bool:
        return instrument_id in self.instrument_ids
