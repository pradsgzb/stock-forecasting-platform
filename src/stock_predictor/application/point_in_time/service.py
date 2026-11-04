"""Leakage-safe price history and derived adjustment views."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from stock_predictor.domain.common.errors import (
    DomainValidationError,
    PointInTimeViolationError,
)
from stock_predictor.domain.common.identifiers import InstrumentId
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.contracts import BarFrequency
from stock_predictor.domain.market_data.features import FeatureInputBar
from stock_predictor.domain.market_data.point_in_time import NormalizedPriceBar
from stock_predictor.ports.calendar_provider import CalendarProvider
from stock_predictor.ports.instrument_repository import InstrumentRepository
from stock_predictor.ports.price_bar_repository import (
    AdjustmentFactorRepository,
    PriceBarRepository,
)


class PointInTimePriceService:
    """Builds historical views using only revisions available by a decision cutoff."""

    __slots__ = ("_adjustments", "_bars", "_calendars", "_instruments")

    def __init__(
        self,
        bars: PriceBarRepository,
        adjustments: AdjustmentFactorRepository,
        instruments: InstrumentRepository,
        calendars: CalendarProvider,
    ) -> None:
        self._bars = bars
        self._adjustments = adjustments
        self._instruments = instruments
        self._calendars = calendars

    def raw_history(
        self,
        instrument_id: InstrumentId,
        start: date,
        end: date,
        cutoff: UtcInstant,
        *,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> tuple[NormalizedPriceBar, ...]:
        bars = self._bars.query_as_known_at(instrument_id, start, end, frequency, cutoff)
        if any(not item.available_by(cutoff) for item in bars):
            raise PointInTimeViolationError("Repository returned data unavailable at cutoff")
        return bars

    def feature_history(
        self,
        instrument_id: InstrumentId,
        as_of: date,
        decision_cutoff: UtcInstant,
        history_size: int,
        *,
        adjusted: bool = True,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> tuple[FeatureInputBar, ...]:
        if history_size <= 0:
            raise DomainValidationError("Feature history size must be positive")
        instrument = self._instruments.get(instrument_id)
        mic = instrument.primary_exchange_mic
        session = self._calendars.session_or_none(mic, as_of)
        if session is None:
            session = self._calendars.previous_session(mic, as_of)
        start_session = session
        for _ in range(history_size - 1):
            start_session = self._calendars.previous_session(mic, start_session.session_date)
        return self.price_path(
            instrument_id,
            start_session.session_date,
            session.session_date,
            decision_cutoff,
            adjusted=adjusted,
            frequency=frequency,
        )

    def price_path(
        self,
        instrument_id: InstrumentId,
        start: date,
        end: date,
        cutoff: UtcInstant,
        *,
        adjusted: bool = True,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> tuple[FeatureInputBar, ...]:
        """Return a point-in-time price path adjusted to the final session in the range."""
        if end < start:
            raise DomainValidationError("Price-path end cannot precede start")
        instrument = self._instruments.get(instrument_id)
        mic = instrument.primary_exchange_mic
        start_session = self._calendars.session(mic, start)
        end_session = self._calendars.session(mic, end)
        bars = self.raw_history(
            instrument_id,
            start_session.session_date,
            end_session.session_date,
            cutoff,
            frequency=frequency,
        )
        factors = (
            self._adjustments.factors_as_known_at(instrument_id, cutoff)
            if adjusted
            else ()
        )
        result: list[FeatureInputBar] = []
        for bar in bars:
            if bar.values is None:
                continue
            applicable = tuple(
                factor
                for factor in factors
                if bar.key.session_date < factor.effective_on <= end_session.session_date
            )
            price_multiplier = self._product(
                tuple(item.price_multiplier for item in applicable)
            )
            volume_multiplier = self._product(
                tuple(item.volume_multiplier for item in applicable)
            )
            available_at = max(
                (bar.normalized_at, *(item.timeline.processed_at for item in applicable)),
                default=bar.normalized_at,
            )
            if available_at > cutoff:
                raise PointInTimeViolationError(
                    "Adjustment or bar became available after the requested cutoff"
                )
            source_payload = "|".join(
                (
                    bar.fingerprint,
                    *(
                        f"{item.factor_id}:{item.revision}:{item.price_multiplier}:"
                        f"{item.volume_multiplier}"
                        for item in applicable
                    ),
                )
            ).encode("utf-8")
            result.append(
                FeatureInputBar(
                    bar_id=bar.bar_id,
                    session_date=bar.key.session_date,
                    open_price=bar.values.open_price.amount * price_multiplier,
                    high_price=bar.values.high_price.amount * price_multiplier,
                    low_price=bar.values.low_price.amount * price_multiplier,
                    close_price=bar.values.close_price.amount * price_multiplier,
                    volume=bar.values.volume.value * volume_multiplier,
                    available_at=available_at,
                    source_fingerprint=hashlib.sha256(source_payload).hexdigest(),
                )
            )
        return tuple(sorted(result, key=lambda item: item.session_date))

    @staticmethod
    def input_fingerprint(history: tuple[FeatureInputBar, ...]) -> str:
        payload = "|".join(
            f"{item.bar_id}:{item.session_date}:{item.source_fingerprint}" for item in history
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _product(values: tuple[Decimal, ...]) -> Decimal:
        result = Decimal(1)
        for value in values:
            result *= value
        return result
