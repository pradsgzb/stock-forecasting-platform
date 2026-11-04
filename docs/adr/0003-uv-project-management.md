# ADR-0003: Use uv for Project and Dependency Management

- Status: Accepted
- Date: 2026-11-03

## Decision

Use standard `pyproject.toml` metadata and uv for environment creation, dependency resolution,
locking, command execution, and package builds.

## Consequences

Local and CI commands remain consistent and fast. The lockfile becomes a reviewed build input.
The package remains standards-based and can still be installed by other PEP 517 tools.
