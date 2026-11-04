# ADR 0021: Layered software-supply-chain controls

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

A passing unit-test suite does not establish that dependencies, workflows, containers, secrets,
or release artifacts are trustworthy.

## Decision

Require lockfile-controlled builds, dependency audit, CodeQL, dependency review, filesystem and
container scanning, secret detection, non-root containers, SBOM generation, checksums, and release
provenance attestation. Pin third-party GitHub Actions to immutable commit identifiers.

## Consequences

- Tagged releases fail when the lockfile or security gates are absent.
- Vulnerability exceptions require a reviewed, time-bounded risk record.
- Release artifacts can be associated with their workflow identity and source revision.
- Tool findings remain evidence for review, not proof of complete security.
