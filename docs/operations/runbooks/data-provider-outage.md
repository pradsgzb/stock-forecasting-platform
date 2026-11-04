# Runbook: market-data provider outage

## Trigger

Provider health check fails, ingestion exceeds its freshness SLO, rate limits persist, or reconciliation cannot complete.

## Immediate actions

1. Stop dependent training and prediction workflows; do not substitute stale data silently.
2. Record provider, request scope, checkpoint, last successful acquisition, correlation ID, and affected instruments.
3. Confirm whether the failure is authentication, authorization, quota, schema, transport, or provider service health.
4. Preserve failed responses and error metadata without logging credentials.
5. Notify the operational owner when the freshness threshold is breached.

## Recovery

1. Restore credentials or connectivity through the approved secret and network process.
2. Resume from the durable ingestion checkpoint.
3. Reconcile page counts, checksums, corrections, and the expected trading calendar.
4. Rerun data-quality gates.
5. Release downstream workflows only after accepted data is present and freshness is restored.

## Prohibited shortcuts

- Marking missing observations as zero.
- Bypassing quarantine or quality gates.
- Reusing an expired provider token in source code.
- Filling historical gaps from a second vendor without recording provider lineage and mapping differences.

## Evidence

Retain incident timeline, affected manifests, checkpoint IDs, quality reports, provider communication, recovery validation, and post-incident action items.
