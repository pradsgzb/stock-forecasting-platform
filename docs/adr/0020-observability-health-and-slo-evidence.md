# ADR 0020: OpenTelemetry, Prometheus, health checks, and immutable SLO evidence

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

Operational failures must be diagnosable without placing account, user, instrument, prediction,
or other high-cardinality identifiers in telemetry.

## Decision

Use OpenTelemetry-compatible spans and Prometheus metrics through a telemetry port. Expose
separate liveness and readiness checks. Persist SLO evaluations as immutable exact-decimal
snapshots instead of deriving historical evidence from mutable dashboards.

## Consequences

- Telemetry vendors remain replaceable.
- Metrics use bounded route, method, status, and operation labels.
- Readiness can fail independently from liveness.
- SLO history is reviewable even when the monitoring backend changes.
