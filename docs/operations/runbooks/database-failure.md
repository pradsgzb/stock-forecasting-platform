# Runbook: operational database failure

## Immediate actions

1. Stop writes when consistency or durability is uncertain.
2. Preserve database, application, and infrastructure timestamps and incident identifiers.
3. Determine whether the issue is connection exhaustion, storage, failover, corruption, migration, network, or credential related.
4. Keep the API unready until required components are healthy.

## Recovery order

1. Restore the managed database or promote the approved standby.
2. Confirm encryption, network policy, and service identity.
3. Run database integrity checks and verify migration revision.
4. Reconcile audit-chain continuity, transactional outbox state, idempotency records, predictions, and outcomes.
5. Resume the worker before accepting new external writes where required by the recovery plan.
6. Exercise a bounded API write and read path.

Never edit or truncate audit and outbox tables merely to make readiness pass. Use compensating events and approved recovery procedures.
