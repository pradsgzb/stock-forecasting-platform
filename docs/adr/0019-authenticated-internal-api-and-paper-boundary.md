# ADR 0019: Authenticated internal API with a paper-only execution boundary

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

Operational users require a stable API and dashboard, but exposing model or financial state
without strong authentication, authorization, abuse controls, and an explicit execution boundary
would create unacceptable risk.

## Decision

Use FastAPI as an inbound adapter. Validate signed JWTs against configured issuer, audience,
verification key, and allow-listed algorithms. Enforce roles server side. Represent all financial
numbers as decimal strings at the HTTP boundary. Provide paper-account operations only; do not
define a broker port or live-order endpoint.

## Consequences

- API schemas are generated and testable without coupling the domain to FastAPI.
- Authentication can be replaced through the `Authenticator` port.
- Owner scoping and privileged audit access are executable policies.
- API documentation is disabled in managed environments unless explicitly reviewed.
- A future live-trading initiative requires a separate ADR, threat model, and risk approval.
