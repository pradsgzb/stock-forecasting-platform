"""Market-time policies independent of external calendar libraries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market.calendar import TradingSession


@dataclass(frozen=True, slots=True)
class MarketDecisionPolicy:
    """Defines safe post-close data and decision timing.

    A decision cannot be generated until the configured ingestion/validation delay has passed.
    Execution timing remains a later backtesting concern.
    """

    close_to_data_cutoff: timedelta = timedelta(minutes=30)
    cutoff_to_decision: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if self.close_to_data_cutoff < timedelta() or self.cutoff_to_decision < timedelta():
            msg = "Market decision delays cannot be negative"
            raise DomainValidationError(msg)

    def data_cutoff(self, session: TradingSession) -> UtcInstant:
        return session.closes_at.plus(self.close_to_data_cutoff)

    def earliest_decision_time(self, session: TradingSession) -> UtcInstant:
        return self.data_cutoff(session).plus(self.cutoff_to_decision)
