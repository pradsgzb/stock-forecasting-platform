"""Point-in-time target-label generation for daily equity research."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from stock_predictor.application.point_in_time.service import PointInTimePriceService
from stock_predictor.domain.common.errors import LabelComputationError
from stock_predictor.domain.common.identifiers import (
    InstrumentId,
    LabelId,
    PriceBarId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.features import FeatureInputBar
from stock_predictor.domain.modeling.targets import (
    LabelObservation,
    TargetDefinition,
    TargetKind,
)
from stock_predictor.ports.calendar_provider import CalendarProvider
from stock_predictor.ports.instrument_repository import InstrumentRepository


class TargetLabelService:
    """Generates realized labels using only data available by the outcome cutoff."""

    __slots__ = ("_calendars", "_instruments", "_prices")

    def __init__(
        self,
        prices: PointInTimePriceService,
        instruments: InstrumentRepository,
        calendars: CalendarProvider,
    ) -> None:
        self._prices = prices
        self._instruments = instruments
        self._calendars = calendars

    def calculate(
        self,
        target: TargetDefinition,
        instrument_id: InstrumentId,
        as_of: date,
        outcome_cutoff: UtcInstant,
    ) -> LabelObservation:
        if not isinstance(as_of, date):
            raise LabelComputationError("Label as-of value must be a date")
        if target.kind is TargetKind.CROSS_SECTIONAL_RANK:
            raise LabelComputationError(
                "Cross-sectional ranks require a peer group; use rank_cross_section"
            )
        path, horizon_end = self._path(
            instrument_id,
            as_of,
            target.horizon.amount,
            outcome_cutoff,
        )
        expected = target.horizon.amount + 1
        if len(path) != expected:
            return self._missing(
                target,
                instrument_id,
                as_of,
                horizon_end,
                outcome_cutoff,
                path,
                f"expected {expected} sessions but found {len(path)}",
            )
        value, additional_source_ids = self._calculate_value(
            target, path, outcome_cutoff, as_of
        )
        available_at = max(item.available_at for item in path)
        source_bar_ids = tuple(
            dict.fromkeys(
                (*tuple(item.bar_id for item in path), *additional_source_ids)
            )
        )
        return LabelObservation(
            label_id=LabelId.new(),
            target=target,
            instrument_id=instrument_id,
            as_of=as_of,
            horizon_end=horizon_end,
            outcome_cutoff=outcome_cutoff,
            available_at=available_at,
            value=value,
            missing_reason=None,
            source_bar_ids=source_bar_ids,
        )

    def rank_cross_section(
        self,
        rank_target: TargetDefinition,
        labels: tuple[LabelObservation, ...],
    ) -> tuple[LabelObservation, ...]:
        """Convert same-date continuous labels to percentile ranks with average ties."""
        if rank_target.kind is not TargetKind.CROSS_SECTIONAL_RANK:
            raise LabelComputationError("Rank target must use cross_sectional_rank kind")
        valid = tuple(item for item in labels if item.value is not None)
        if not valid:
            raise LabelComputationError("Cross-sectional ranking requires valid labels")
        reference = valid[0]
        if any(
            item.as_of != reference.as_of or item.horizon_end != reference.horizon_end
            for item in labels
        ):
            raise LabelComputationError(
                "Cross-sectional labels must share as-of and horizon-end dates"
            )
        if any(item.outcome_cutoff != reference.outcome_cutoff for item in labels):
            raise LabelComputationError(
                "Cross-sectional labels must share one outcome cutoff"
            )
        if len({item.target.fingerprint for item in labels}) != 1:
            raise LabelComputationError(
                "Cross-sectional labels must share one source target definition"
            )
        if any(isinstance(item.value, int) for item in valid):
            raise LabelComputationError("Cross-sectional ranking requires continuous labels")
        ordered_values = sorted(Decimal(item.value) for item in valid if item.value is not None)
        denominator = Decimal(max(len(ordered_values) - 1, 1))
        group_available_at = max(item.available_at for item in labels)
        peer_source_ids = tuple(
            sorted(
                {
                    source_id
                    for item in labels
                    for source_id in item.source_bar_ids
                },
                key=str,
            )
        )
        result: list[LabelObservation] = []
        for item in labels:
            if item.value is None:
                result.append(
                    LabelObservation(
                        label_id=LabelId.new(),
                        target=rank_target,
                        instrument_id=item.instrument_id,
                        as_of=item.as_of,
                        horizon_end=item.horizon_end,
                        outcome_cutoff=item.outcome_cutoff,
                        available_at=group_available_at,
                        value=None,
                        missing_reason=item.missing_reason or "source label missing",
                        source_bar_ids=peer_source_ids,
                    )
                )
                continue
            value = Decimal(item.value)
            positions = tuple(
                index for index, candidate in enumerate(ordered_values) if candidate == value
            )
            mean_position = Decimal(sum(positions)) / Decimal(len(positions))
            percentile = mean_position / denominator if len(ordered_values) > 1 else Decimal("0.5")
            result.append(
                LabelObservation(
                    label_id=LabelId.new(),
                    target=rank_target,
                    instrument_id=item.instrument_id,
                    as_of=item.as_of,
                    horizon_end=item.horizon_end,
                    outcome_cutoff=item.outcome_cutoff,
                    available_at=group_available_at,
                    value=percentile,
                    missing_reason=None,
                    source_bar_ids=peer_source_ids,
                )
            )
        return tuple(result)

    def _path(
        self,
        instrument_id: InstrumentId,
        as_of: date,
        horizon: int,
        outcome_cutoff: UtcInstant,
    ) -> tuple[tuple[FeatureInputBar, ...], date]:
        instrument = self._instruments.get(instrument_id)
        mic = instrument.primary_exchange_mic
        start_session = self._calendars.session(mic, as_of)
        end_session = start_session
        for _ in range(horizon):
            end_session = self._calendars.next_session(mic, end_session.session_date)
        if end_session.closes_at > outcome_cutoff:
            raise LabelComputationError(
                "Outcome cutoff occurs before the target trading session closes"
            )
        path = self._prices.price_path(
            instrument_id,
            start_session.session_date,
            end_session.session_date,
            outcome_cutoff,
            adjusted=True,
        )
        return path, end_session.session_date

    def _calculate_value(
        self,
        target: TargetDefinition,
        path: tuple[FeatureInputBar, ...],
        outcome_cutoff: UtcInstant,
        as_of: date,
    ) -> tuple[Decimal | int, tuple[PriceBarId, ...]]:
        start = path[0].close_price
        end = path[-1].close_price
        simple_return = (end / start) - Decimal(1)
        if target.kind is TargetKind.SIMPLE_RETURN:
            return simple_return, ()
        if target.kind is TargetKind.LOG_RETURN:
            with localcontext() as context:
                context.prec = 34
                return (end / start).ln(), ()
        if target.kind is TargetKind.DIRECTION:
            return int(simple_return > target.positive_threshold), ()
        if target.kind is TargetKind.REALIZED_VOLATILITY:
            returns = tuple(
                (current.close_price / previous.close_price) - Decimal(1)
                for previous, current in zip(path, path[1:])
            )
            mean = sum(returns, start=Decimal(0)) / Decimal(len(returns))
            variance = sum(
                ((item - mean) ** 2 for item in returns),
                start=Decimal(0),
            ) / Decimal(len(returns) - 1)
            with localcontext() as context:
                context.prec = 34
                return (
                    variance.sqrt() * Decimal(target.annualization_sessions).sqrt(),
                    (),
                )
        if target.kind is TargetKind.MAX_ADVERSE_EXCURSION:
            return (
                min((item.low_price / start) - Decimal(1) for item in path[1:]),
                (),
            )
        if target.kind is TargetKind.MAX_FAVORABLE_EXCURSION:
            return (
                max((item.high_price / start) - Decimal(1) for item in path[1:]),
                (),
            )
        if target.kind is TargetKind.RELATIVE_RETURN:
            benchmark_id = target.benchmark_instrument_id
            if benchmark_id is None:  # Defensive: target validation already enforces this.
                raise LabelComputationError("Relative target has no benchmark")
            benchmark_path, _ = self._path(
                benchmark_id,
                as_of,
                target.horizon.amount,
                outcome_cutoff,
            )
            expected = target.horizon.amount + 1
            if len(benchmark_path) != expected:
                raise LabelComputationError("Benchmark path is incomplete")
            benchmark_return = (
                benchmark_path[-1].close_price / benchmark_path[0].close_price
            ) - Decimal(1)
            return (
                simple_return - benchmark_return,
                tuple(item.bar_id for item in benchmark_path),
            )
        raise LabelComputationError(f"Unsupported target kind: {target.kind.value}")

    @staticmethod
    def _missing(
        target: TargetDefinition,
        instrument_id: InstrumentId,
        as_of: date,
        horizon_end: date,
        outcome_cutoff: UtcInstant,
        path: tuple[FeatureInputBar, ...],
        reason: str,
    ) -> LabelObservation:
        available_at = max(
            (item.available_at for item in path),
            default=outcome_cutoff,
        )
        return LabelObservation(
            label_id=LabelId.new(),
            target=target,
            instrument_id=instrument_id,
            as_of=as_of,
            horizon_end=horizon_end,
            outcome_cutoff=outcome_cutoff,
            available_at=available_at,
            value=None,
            missing_reason=reason,
            source_bar_ids=tuple(item.bar_id for item in path),
        )
