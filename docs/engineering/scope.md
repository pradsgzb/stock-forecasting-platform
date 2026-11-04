# Scope and System Boundary

## In scope through Section 25

- Engineering governance, Clean/Hexagonal architecture, packaging, CI/CD, and tests
- Strong domain values, instrument identity, exchange calendars, and market-time semantics
- Market-data provider SDK, immutable ingestion, validation, normalization, and point-in-time
  corrections
- Versioned feature calculations and source lineage
- Versioned targets and future labels
- Immutable supervised-learning datasets
- Purged walk-forward validation and an untouched final holdout
- Replaceable model plugins and mandatory baselines
- Deterministic search, training, experiment evidence, model cards, and checksummed artifacts
- Predictive metrics, calibration, confidence intervals, cohort slices, and importance evidence
- Long-only, next-session, transaction-cost-aware paper backtesting with risk limits and
  benchmark comparison
- Governed model registry, lifecycle transitions, approvals, champion/challenger aliases, and
  deployment history
- Batch-first inference and an immutable prediction/correction ledger
- Realized-outcome revisions, feedback metrics, distribution drift, and performance monitoring
- Durable retraining requests, shadow/canary challengers, controlled promotion, and rollback
- SQLAlchemy operational unit of work, exact-decimal persistence, packaged Alembic migrations,
  idempotency, hash-chained audit, and transactional outbox
- Authenticated internal operations API, paper-account workflows, and minimal dashboard
- Prometheus/OpenTelemetry-compatible telemetry, health checks, and immutable SLO evidence
- Expanded persistence, migration, authentication, authorization, abuse, and end-to-end tests
- Code, dependency, filesystem, secret, configuration, container, SBOM, and provenance controls

## Out of scope

- Distributed/cloud adapters for every high-volume research repository and licensed vendor connectors
- Public consumer API or consumer-facing dashboard
- Arbitrary automatic promotion outside configured policy and evidence gates
- Autonomous source-code modification
- Broker connectivity, live orders, short selling, leverage, or fiduciary services
- Personalized financial advice or guaranteed outcomes
- An authoritative NSE calendar; `XNSE` must not be silently mapped to `XBOM`

## Trust boundaries

1. **Configuration:** environment and secret sources are untrusted until validated.
2. **Market-data adapters:** provider payloads and calendar libraries are external inputs.
3. **Persistence:** repository and object-store implementations are replaceable adapters.
4. **Model plugins:** plugins are trusted operator-installed code, not arbitrary user code.
5. **Model artifacts:** checksums detect corruption; only authorized sources establish trust,
   and deserialization is disabled by default.
6. **Registry:** aliases and deployments are trusted only after atomic policy-controlled commits.
7. **Inference:** callers provide requests, but the service resolves the champion and enforces
   signatures server-side.
8. **Prediction/outcome evidence:** corrections append records and cannot mutate history.
9. **Monitoring:** alerts are evidence for review, retraining, or rollback—not proof that a new
   model is superior.
10. **Backtest inputs:** signals and bars are research evidence, never executable broker orders.
11. **API boundary:** request payloads are authenticated, authorized, bounded, and validated
   before application services execute.
12. **Operational database:** the transaction is the durability boundary for acknowledged paper,
   idempotency, audit, and outbox writes.
13. **Telemetry:** metrics and traces are external sinks and must not receive secrets or
   high-cardinality business identifiers.

## Legal and financial boundary

This software is research and engineering infrastructure. It does not provide financial advice,
a fiduciary service, brokerage, or guaranteed outcome. Data licenses, exchange rules,
regulatory obligations, taxation, and deployment jurisdiction remain the operator's
responsibility.
