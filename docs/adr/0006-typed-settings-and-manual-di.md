# ADR-0006: Use Typed Settings and Manual Dependency Injection

- Status: Accepted
- Date: 2026-11-03

## Decision

Use pydantic-settings at the configuration boundary. Use an explicit `ApplicationContainer`
factory rather than a global service locator or dependency-injection framework.

## Consequences

Startup failures are early and understandable. Dependencies remain visible to readers and easy
to replace in tests. The bootstrap layer, not the domain, owns Pydantic.
