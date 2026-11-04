# ADR-0008: Use Decimal, UTC Instants, and Half-Open Effective Periods

- Status: Accepted
- Date: 2026-11-03

## Decision

Represent financial values with `Decimal`; reject floats. Normalize canonical instants to UTC
while retaining exchange-local session labels. Represent effective periods as `[start, end)`.

## Consequences

Arithmetic avoids binary rounding surprises. Time-zone ambiguity is reduced. Adjacent symbol
periods can meet at one date without overlap.
