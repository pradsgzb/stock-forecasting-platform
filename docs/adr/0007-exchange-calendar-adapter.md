# ADR-0007: Isolate exchange_calendars Behind a Port

- Status: Accepted
- Date: 2026-11-03

## Context

Trading holidays, early closes, breaks, and historical changes are too complex for naive
weekday logic. No third-party library should become an implicit domain model.

## Decision

Use `exchange_calendars` as the initial implementation of `CalendarProvider`. Convert all
library timestamps to validated domain sessions. Keep exchange-to-calendar mappings explicit.

## Consequences

The platform gains broad venue coverage while preserving the ability to replace or supplement
calendar sources. Unsupported NSE coverage remains explicit rather than approximated.
