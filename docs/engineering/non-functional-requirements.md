# Nonfunctional Requirements

## Correctness

- All financial arithmetic uses `Decimal` or integers.
- All persisted instants are timezone-aware and normalized to UTC.
- Effective periods use inclusive start and exclusive end semantics.
- No venue calendar may be substituted silently.
- Domain invariants fail fast with explicit exceptions.
- Model, alias, deployment, prediction, outcome, paper-account, audit, outbox, and SLO state
  changes are append-only or optimistic-concurrency controlled.
- Acknowledged operational writes are durably committed before a success response is returned.

## Maintainability

- Public functions and classes are typed.
- Domain modules have no third-party framework dependencies.
- Cyclomatic complexity is limited by linting.
- Each defect receives a regression test.
- Architecture decisions are recorded before introducing strategic dependencies.
- Service boundaries use ports so in-memory reference stores can be replaced without changing
  domain or application behavior.

## Reproducibility

- The Python compatibility range and direct dependencies are declared in `pyproject.toml`.
- CI uses an immutable dependency lock once generated in a networked environment.
- Runs record code, configuration, data, feature, target, model, and artifact versions.
- Predictions record the exact model and input fingerprints before outcomes mature.
- Feedback, monitoring, and promotion decisions retain source-evidence fingerprints.

## Security

- Secrets are never logged or committed.
- Production debug mode is rejected.
- Trusted model deserialization is disabled by default.
- Online inference and automatic promotion are disabled by default.
- Dependencies are audited and updated through reviewed pull requests.
- CI performs static analysis, dependency review, dependency audit, secret/configuration scan,
  and container vulnerability scan.
- JWT verification uses explicit issuer, audience, key, time-claim, and algorithm policy.
- Sensitive identifiers are excluded from metric labels and ordinary logs.

## Portability

- Core logic is operating-system independent.
- IANA timezone data is available on Windows through `tzdata`.
- Provider, calendar, persistence, model, and monitoring integrations are replaceable adapters.

## Performance baseline

The platform is optimized for correctness and end-of-day batch work, not high-frequency
trading. Batch size is bounded by validated configuration. Online inference is an optional
future mode and disabled by default.

## Reliability

- Adapter failures are explicit; no silent empty result is returned for unavailable calendars.
- Configuration is validated before service startup.
- Immutable value objects prevent accidental mutation across threads.
- Idempotency keys protect ingestion, inference, and retraining against duplicate execution.
- Registry mutations reject stale revisions and conflicting active deployments.
- Critical champion degradation has a tested predecessor rollback path.
- Transactional outbox publication survives downstream failure and supports controlled replay.
- Readiness independently verifies database access and audit-chain integrity.
