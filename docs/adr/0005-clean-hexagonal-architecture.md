# ADR-0005: Apply Clean and Hexagonal Architecture

- Status: Accepted
- Date: 2026-11-03

## Decision

Keep domain objects independent of frameworks. Define outbound needs as ports owned by the
core. Implement integrations as adapters. Perform concrete wiring in a composition root.

## Consequences

Third-party calendar, persistence, provider, and cloud choices remain replaceable. Additional
interfaces add some code, so ports are introduced only at genuine external boundaries.
