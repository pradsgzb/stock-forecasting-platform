# Runbook: prediction generation failure

## Trigger

Scheduled inference does not complete, model resolution fails, features are unavailable, signature validation fails, or output validation rejects a prediction.

## Immediate actions

1. Do not emit a placeholder prediction or reuse a prior prediction as current.
2. Record batch idempotency key, model scope, champion version, feature set, as-of time, and decision cutoff.
3. Determine whether the failure affects one instrument or the complete batch.
4. Preserve successful per-instrument results only when the batch policy explicitly supports partial success.
5. Alert when the prediction completion SLO is breached.

## Recovery

1. Restore data freshness and feature availability.
2. Confirm the champion artifact checksum and model signature.
3. Retry using the same idempotency key when policy permits.
4. Verify the immutable prediction ledger contains no duplicate semantic prediction.
5. Record the final disposition and any missed prediction window.
