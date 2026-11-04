# Changelog

## 0.6.0 - 2026-11-04

### Added

- immutable software release manifests, promotion plans, and artifact verification;
- locked CI, controlled Kubernetes delivery, and continuous-training qualification workflows;
- production and debugger containers, Docker Compose profiles, and VS Code debug tasks;
- Kubernetes integration, staging, and production overlays with migration-first delivery;
- GCP and Azure Terraform reference deployments using managed identities and external secrets;
- setup, run, debug, deployment, governance, and incident-response documentation;
- versioned student learning catalog and exercise briefs; and
- executable end-to-end reference scenario covering ingestion through monitored rollback.

### Changed

- package version advanced to 0.6.0;
- local API identity may be supplied by a mounted public-key file; and
- release and repository validation now enforce immutable artifact and deployment evidence.

All notable changes are documented here. The format follows Keep a Changelog and the project
uses Semantic Versioning.

## [Unreleased]

### Added

- SQLAlchemy 2 operational unit of work with exact-decimal persistence and optimistic concurrency.
- Packaged Alembic migration for audit, outbox, idempotency, paper-account, and SLO state.
- Hash-chained append-only audit ledger and transactional outbox dispatcher.
- Principal-scoped paper accounts, orders, fills, positions, idempotent replay, and risk controls.
- Signed-JWT authentication, role authorization, trusted hosts, request/body limits, and sanitized
  RFC 9457-style API errors.
- Versioned FastAPI operations API, internal dashboard, protected metrics, liveness, and readiness.
- Prometheus/OpenTelemetry-compatible telemetry and immutable exact-decimal SLO snapshots.
- Persistence contracts, migration tests, JWT/authorization/abuse tests, and secured API vertical slice.
- Sections 21–25 engineering specification, operational architecture, threat model, ADRs, and runbooks.
- Filesystem, secret, configuration, and container scanning workflow with pinned actions.
- Append-only governed model registry with lifecycle transitions, approvals, promotion gates,
  scoped champion/challenger aliases, and deployment history.
- Batch-first champion inference with signature validation, request idempotency, and immutable
  prediction batches and correction records.
- Strict realized-outcome revision chains, target-version reconciliation, and feedback metrics.
- Feature/prediction distribution drift and realized-performance monitoring with append-only
  warning and critical alerts.
- Durable retraining requests, shadow challengers, minimum-evidence comparison, human-gated
  promotion, policy-controlled promotion option, and critical-alert rollback.
- Sections 16–20 engineering specification, production-MLOps architecture, and ADRs.
- End-to-end prediction, outcome, monitoring, retraining, promotion, and rollback integration test.
- Versioned future-return, direction, volatility, relative-return, rank, and excursion targets.
- Point-in-time label generation with target, benchmark, and peer-group source lineage.
- Immutable supervised-learning datasets and deterministic content fingerprints.
- Purged expanding/rolling walk-forward splits with gaps, embargo, and final holdout.
- Task-aware model plugin SDK and validated plugin registry.
- Zero-return, historical-mean, feature-echo, and majority baselines.
- Ridge, logistic, and random-forest model adapters.
- Bounded deterministic grid and random candidate search.
- Append-only experiment trackers, model cards, and checksummed trusted-artifact codec.
- Regression and classification metrics, calibration, bootstrap intervals, slice analysis,
  permutation importance, and native importance.
- Long-only next-session paper backtester with cost, liquidity, turnover, exposure, and drawdown
  controls.
- Benchmark total return, active return, tracking error, and deterministic backtest fingerprints.
- Sections 11–15 architecture specifications and ADRs.
- End-to-end dataset, training, artifact, prediction, and paper-backtest integration test.

### Changed

- Package version advanced to `0.5.0`.
- Composition root now also wires operational persistence, paper trading, health, SLO, telemetry,
  and outbox services.
- Managed API startup now requires PostgreSQL, a verification key, disabled interactive docs, and
  explicit host/JWT policy.
- API reference rate-limit state is bounded; distributed deployments must replace it with a
  shared atomic limiter.
- Composition root now also wires registry, prediction ledger, outcome, feedback, monitoring,
  and continuous-training services.
- Settings now enforce research-only backtesting and trusted-artifact loading defaults.
- Dataset and backtest fingerprints now exclude generated IDs and publication timestamps that do
  not change economic content.
- Required baselines must all complete successfully before candidate evidence is accepted.

### Security

- Added JWT signature/issuer/audience/time-claim validation and server-side role enforcement.
- Added trusted-host, security-header, body-limit, bounded rate-limit, sanitized-error, and
  sensitive-telemetry controls.
- Added Trivy source/configuration/secret and container scanning provisions.
- Model artifact deserialization remains disabled unless explicitly enabled for trusted content.
- Live trading remains prohibited in configuration and no broker interface is present.
- Trusted artifact loading remains disabled by default; online inference and automatic model
  promotion are disabled by default.

## [0.2.0]

### Added

- Vendor-neutral, capability-declared market-data provider SDK.
- Immutable raw-object storage, resumable ingestion, quality controls, point-in-time revisions,
  and versioned feature materialization through Sections 06–10.
