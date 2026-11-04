from collections.abc import Iterator
from typing import cast

import pytest

from stock_predictor.application.operations.outbox import OutboxDispatchResult, OutboxDispatcher
from stock_predictor.application.workers.outbox import run_outbox_worker


class _Dispatcher:
    def __init__(self, results: Iterator[OutboxDispatchResult]) -> None:
        self.results = results
        self.limits: list[int] = []

    def dispatch(self, *, limit: int = 100) -> OutboxDispatchResult:
        self.limits.append(limit)
        return next(self.results)


def test_outbox_worker_once_returns_one_dispatch() -> None:
    dispatcher = _Dispatcher(iter((OutboxDispatchResult(2, 1, 1, 0),)))

    result = run_outbox_worker(cast(OutboxDispatcher, dispatcher), limit=12, once=True)

    assert result == OutboxDispatchResult(2, 1, 1, 0)
    assert dispatcher.limits == [12]


def test_outbox_worker_polls_when_empty_and_aggregates() -> None:
    dispatcher = _Dispatcher(
        iter(
            (
                OutboxDispatchResult(0, 0, 0, 0),
                OutboxDispatchResult(2, 2, 0, 0),
            )
        )
    )
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            return

    with pytest.raises(StopIteration):
        run_outbox_worker(
            cast(OutboxDispatcher, dispatcher),
            poll_seconds=0.25,
            sleep=sleep,
        )

    assert sleeps == [0.25]
    assert dispatcher.limits == [100, 100, 100]


def test_outbox_worker_rejects_invalid_bounds() -> None:
    dispatcher = cast(OutboxDispatcher, _Dispatcher(iter(())))
    with pytest.raises(ValueError, match="limit"):
        run_outbox_worker(dispatcher, limit=0, once=True)
    with pytest.raises(ValueError, match="interval"):
        run_outbox_worker(dispatcher, poll_seconds=0, once=True)
