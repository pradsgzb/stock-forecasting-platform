# ADR 0013 — Isolate model plugins and require trusted artifact loading

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

The platform must compare diverse estimators without coupling training orchestration to one ML
library. Python model serialization formats such as joblib/pickle can execute arbitrary code
when loaded and must not be accepted from an untrusted source.

## Decision

Models implement a task-aware plugin port. Training, evaluation, and artifact orchestration use
that port rather than estimator-specific APIs. Experiment evidence is append-only. Serialized
artifacts carry SHA-256 checksums and may be deserialized only when the trusted-artifact setting
is explicitly enabled.

Every training request declares mandatory baseline plugin keys. Those baselines must be
included as candidates and complete successfully before the run can produce a final model.

## Consequences

- New model families can be added without changing the training use case.
- Artifact provenance and registry authorization remain required in a later deployment section.
- A checksum detects corruption but does not make an artifact trustworthy.
- Production loading remains disabled by default until signing and registry controls are added.
