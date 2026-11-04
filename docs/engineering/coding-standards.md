# Coding Standards

## Python

- Use Python 3.13-compatible syntax until the compatibility floor changes.
- Use explicit type annotations for public APIs and all domain objects.
- Prefer immutable `dataclass(frozen=True, slots=True)` value objects.
- Use `Decimal` for financial quantities; reject float input at boundaries.
- Use aware `datetime` values and normalize canonical instants to UTC.
- Prefer small pure functions and explicit state transitions.
- Raise domain-specific exceptions with actionable messages.
- Avoid service locators, module-level mutable state, and hidden I/O.

## Architecture

- Domain → standard library only.
- Ports → domain only.
- Application → domain and ports.
- Adapters → domain and ports plus external libraries.
- Bootstrap/CLI → all layers for composition only.

## Error handling

- Never use a bare `except`.
- Never silently return an empty value after an adapter failure.
- Preserve the original exception as a cause when translating boundaries.
- Messages must identify the failed invariant without leaking secrets.

## Documentation

- Public modules, classes, and non-obvious functions require docstrings.
- Explain *why* an invariant exists, not merely what a line does.
- Every strategic choice belongs in an ADR.

## Testing

- Tests describe behavior and business invariants.
- Unit tests avoid wall-clock and network dependencies.
- Integration tests are explicitly marked.
- Time-dependent code receives explicit timestamps or a `Clock`.
- Tests must not depend on execution order.
