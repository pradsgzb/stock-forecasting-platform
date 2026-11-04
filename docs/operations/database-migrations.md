# Database Migration Runbook

## Local initialization

```bash
uv run --locked stock-predictor db-upgrade
uv run --locked stock-predictor db-current
```

The `create_schema_for_testing()` helper is restricted to tests and local demonstrations. Managed
runtimes use Alembic migrations only.

## Managed deployment sequence

1. Back up the database and verify restore evidence.
2. Review the generated SQL and migration risk classification.
3. Quiesce incompatible writers when the migration is not expand-only.
4. Run `stock-predictor db-upgrade` from the exact release image.
5. Verify `stock-predictor db-current` reports the expected revision.
6. Start the application and verify readiness, audit integrity, and smoke tests.
7. Record migration, release, operator, timestamps, and verification evidence.

## Rollback

A downgrade is permitted only when the migration explicitly preserves required data. Otherwise,
restore the pre-change backup into an isolated environment, validate it, and perform a controlled
cutover. Never delete audit, idempotency, outbox, or financial evidence merely to make a downgrade
succeed.
