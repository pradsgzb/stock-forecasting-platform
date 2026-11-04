# ADR 0018: Transactional operational persistence and outbox

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

Paper-account writes, audit evidence, idempotency state, and integration events must not diverge
when a process fails between database operations and external publication.

## Decision

Use SQLAlchemy 2 with an explicit unit of work. Persist the business mutation, idempotency record,
hash-chained audit event, and outbox event in one database transaction. Use Alembic for managed
schema changes. PostgreSQL is the managed-runtime target; SQLite is a local/test compatibility
adapter with exact decimals stored as canonical text.

## Consequences

- A committed operation is reconstructable and replay safe.
- External publication is at least once and consumers must be idempotent.
- Outbox dispatch can resume after failure without inventing a second business transaction.
- Managed deployments must apply migrations before process startup.
- High-volume research data remains behind independent ports and storage policies.
