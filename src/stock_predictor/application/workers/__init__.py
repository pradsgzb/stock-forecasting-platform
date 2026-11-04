"""Process workers."""

from stock_predictor.application.workers.outbox import run_outbox_worker

__all__ = ["run_outbox_worker"]
