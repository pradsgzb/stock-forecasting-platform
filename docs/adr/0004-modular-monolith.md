# ADR-0004: Begin with a Modular Monolith

- Status: Accepted
- Date: 2026-11-03

## Context

The planned platform has many future capabilities, but Sections 00–05 do not justify networked
service boundaries.

## Decision

Use explicit modules and ports inside one deployable package. Extract workers or services only
when scaling, security, availability, deployment cadence, or team ownership provides evidence.

## Consequences

Transactions, testing, and local development stay simple. Module boundaries and dependency
tests preserve future extractability.
