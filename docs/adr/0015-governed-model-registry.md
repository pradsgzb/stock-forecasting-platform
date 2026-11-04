# ADR 0015 — Use an append-only governed model registry

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

A mutable “current model” file cannot prove which artifact was approved, who approved it, which
model it replaced, or how to recover after degradation. Independent writes to lifecycle state,
aliases, and deployment records can also create split-brain serving state.

## Decision

Represent every model version, lifecycle transition, alias binding, approval, gate, and
deployment as immutable evidence. Commit lifecycle, alias, and deployment mutations atomically
through a repository port with optimistic revision checks. Scope champion and challenger aliases
by environment, target key, and learning task.

A candidate must pass configured technical gates and approval roles before deployment. It first
becomes a shadow or canary challenger; only the assigned challenger may become champion.

## Consequences

- Promotion and rollback are reconstructable and concurrency-safe.
- Registry storage adapters must support atomic release commits.
- In-memory storage is a reference adapter only; durable deployments require transactional
  persistence and retention controls.
- Alias lookup is convenient serving state, not a substitute for lifecycle history.
