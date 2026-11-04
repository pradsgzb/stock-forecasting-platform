# ADR 0016 — Preserve predictions and realized outcomes as immutable ledgers

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

A forecasting system can overstate quality if historical predictions are regenerated or edited
after prices are known. Market-data corrections also require revised outcomes without erasing
what the system originally observed.

## Decision

Persist predictions before outcomes mature with complete model, artifact, signature, feature,
input, time, and target lineage. Make batch submission idempotent. Never update a prediction in
place; corrections are new records linked to the original and preserve immutable business
identity.

Persist realized outcomes as strict revisions. Each revision links to the exact label
fingerprint and supersedes the prior revision. Feedback uses the latest outcome revision while
history remains available for audit.

## Consequences

- Historical performance can be reproduced without hindsight edits.
- Corrections increase storage but preserve evidence.
- Serving and outcome pipelines require stable idempotency and fingerprint contracts.
- Retention and access controls must protect both original and corrected records.
