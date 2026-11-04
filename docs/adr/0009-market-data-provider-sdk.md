# ADR-0009: Use Capability-Declared Provider Ports and Preserve Opaque Pages

- Status: Accepted
- Date: 2026-11-03

## Context

Market-data vendors expose different symbols, pagination, schemas, rate limits, adjustment
policies, and correction behavior. Allowing vendor SDK types to enter application or domain
logic would make replacement difficult and obscure what was originally received.

## Decision

Define a vendor-neutral `MarketDataProvider` port. Each adapter declares machine-checkable
capabilities, fetches one opaque page at a time, and owns decoding of its page schema. The
application stores the exact page bytes before validation or normalization. Shared retry,
rate-limit, and page-contract safeguards live in `ResilientMarketDataProvider`.

## Consequences

Provider behavior is testable through a common contract and vendor dependencies remain at the
edge. Adapters require explicit mapping work, and a new schema version must be supported by the
owning adapter before its records can pass validation.
