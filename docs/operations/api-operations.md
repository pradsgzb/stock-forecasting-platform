# Operations API Runbook

## Start locally

```bash
uv run --locked stock-predictor db-upgrade
uv run --locked stock-predictor serve
```

A verification key, issuer, audience, allowed hosts, database URL, request-size limit, and rate
policy must be configured before a managed start. Staging and production reject SQLite and reject
interactive API documentation.

## Required probes

- `GET /health/live` confirms the process event loop is responsive.
- `GET /health/ready` confirms database access and audit-chain integrity.
- `GET /metrics` requires the `metrics_reader` or `admin` role.

## Incident signals

Investigate immediately when readiness fails, the audit chain does not verify, outbox backlog
increases, idempotency conflicts spike, API 5xx rate breaches its objective, or paper-account
optimistic-concurrency failures persist.

## Sensitive-data rule

Do not place bearer tokens, private keys, request bodies, account IDs, user IDs, model payloads, or
raw prediction features in ordinary logs or metric labels.
