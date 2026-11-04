"""Bounded polling loop for transactional outbox delivery."""

from __future__ import annotations

import time
from collections.abc import Callable

from stock_predictor.application.operations.outbox import (
    OutboxDispatcher,
    OutboxDispatchResult,
)

Sleep = Callable[[float], None]


def run_outbox_worker(
    dispatcher: OutboxDispatcher,
    *,
    limit: int = 100,
    poll_seconds: float = 5.0,
    once: bool = False,
    sleep: Sleep = time.sleep,
) -> OutboxDispatchResult:
    """Dispatch pending events, sleeping only when a continuous worker finds no work."""
    if limit <= 0:
        raise ValueError("Outbox worker limit must be positive")
    if poll_seconds <= 0:
        raise ValueError("Outbox worker poll interval must be positive")
    aggregate = OutboxDispatchResult(0, 0, 0, 0)
    while True:
        current = dispatcher.dispatch(limit=limit)
        aggregate = OutboxDispatchResult(
            selected=aggregate.selected + current.selected,
            published=aggregate.published + current.published,
            failed=aggregate.failed + current.failed,
            dead_lettered=aggregate.dead_lettered + current.dead_lettered,
        )
        if once:
            return aggregate
        if current.selected == 0:
            sleep(poll_seconds)
