# Product Requirements — Research and Controlled MLOps Through Section 20

## 1. Objective

Create a trustworthy engineering foundation for a stock-forecasting research and controlled
MLOps platform. Data, features, labels, training, evaluation, backtesting, model lifecycle,
predictions, outcomes, feedback, monitoring, retraining, promotion, and rollback must be
reproducible, point-in-time correct, and auditable.

This release implements Sections 00–20. It can govern and serve approved models in batch,
collect realized outcomes, monitor performance, train challengers, and perform controlled
promotion or rollback. It does not issue personalized investment advice, connect to a broker,
place a live order, rewrite its own code, or claim profitable performance.

## 2. Primary users

- Student/research engineer learning production machine learning
- ML engineer implementing training and inference pipelines
- Quantitative researcher defining features, targets, and experiments
- Data engineer integrating licensed market-data providers
- ML operations engineer managing deployments and monitoring
- Model validator, risk owner, and deployment approver
- Platform engineer operating CI/CD and infrastructure
- Reviewer assessing reproducibility, leakage, model risk, and rollback readiness

## 3. Functional requirements

### Foundation and market-data requirements

- **FR-001 Governance:** define scope, assumptions, open decisions, coding standards, quality
  gates, acceptance criteria, and implementation sequence.
- **FR-002 Architecture:** keep domain behavior independent of frameworks, vendors, and
  persistence; compose dependencies at the bootstrap boundary.
- **FR-003 Strong types:** use validated identifiers, exact decimal financial values, UTC
  instants, effective periods, and explicit prediction horizons.
- **FR-004 Configuration:** validate settings at startup, redact secrets, and prohibit unsafe
  production combinations.
- **FR-005 Instrument identity:** separate stable instrument IDs from effective-dated ticker and
  provider mappings.
- **FR-006 Market time:** identify venues with ISO 10383 MICs and use explicit IANA time zones,
  sessions, holidays, early closes, and information-availability times.
- **FR-007 Immutable ingestion:** retain exact provider payloads by checksum, support resumable
  idempotent ingestion, and record immutable manifests.
- **FR-008 Data quality:** decode through the owning adapter, reconcile counts, run versioned
  rules, score quality, and quarantine or reject invalid batches.
- **FR-009 Point-in-time normalization:** append corrections and tombstones without overwriting
  history; apply only factors known by the requested cutoff.
- **FR-010 Feature contracts:** version feature definitions, require lookback/minimum-history
  rules, and preserve exact source lineage and input fingerprints.

### Targets, datasets, training, and backtesting

- **FR-011 Versioned targets:** support return, direction, volatility, benchmark-relative,
  cross-sectional rank, and excursion targets.
- **FR-012 Label evidence:** record as-of date, horizon end, outcome cutoff, availability, source
  bars, benchmark bars, peer-group lineage, target version, and fingerprint.
- **FR-013 Immutable datasets:** build numeric dataset snapshots with row-level source identities,
  deterministic content fingerprints, and explicit missing-data policy.
- **FR-014 Time splitting:** provide purged walk-forward folds, gaps, optional embargo, and one
  untouched final holdout.
- **FR-015 Model plugin contract:** isolate estimator-specific behavior behind a task-aware port
  for fitting, prediction, probability, importance, health checks, and artifacts.
- **FR-016 Mandatory baselines:** require declared naive baselines to be candidates and complete
  successfully before advanced-model evidence is accepted.
- **FR-017 Reference models:** provide baseline, linear, logistic, and tree-ensemble adapters with
  deterministic seeds and validated hyperparameters.
- **FR-018 Training isolation:** tune and select only on development folds; evaluate the final
  holdout only after selection.
- **FR-019 Experiment evidence:** append immutable startup, trial, selection, holdout, artifact,
  completion, and failure events.
- **FR-020 Bounded search:** support deterministic, trial-limited grid and random search.
- **FR-021 Artifact controls:** checksum serialized artifacts and disable unsafe deserialization
  unless the trusted-artifact boundary is explicitly enabled.
- **FR-022 Model cards:** record intended use, prohibited use, data/split lineage, validation and
  holdout scores, limitations, and generation time.
- **FR-023 Predictive evaluation:** calculate task-appropriate regression and classification
  metrics with explicit optimization direction.
- **FR-024 Uncertainty and robustness:** support bootstrap confidence intervals, calibration,
  cohort slices, permutation importance, and native importance.
- **FR-025 Immutable reports:** content-address evaluation reports and retain sample counts and
  evidence metadata.
- **FR-026 Execution timing:** prohibit same-session lookahead; execute only at the next supplied
  session open when a signal was already available.
- **FR-027 Realistic paper costs:** model participation limits, spread, slippage, commission,
  fixed charges, partial fills, and cash constraints.
- **FR-028 Risk controls:** enforce long-only position, gross exposure, turnover, liquidity, and
  drawdown limits and liquidate after a risk halt where data permits.
- **FR-029 Economic evidence:** report return, risk, drawdown, turnover, costs, trades, benchmark
  return, active return, and tracking error.
- **FR-030 Deterministic backtests:** produce content fingerprints independent of generated run,
  order, and fill identifiers.
- **FR-031 Paper-only boundary:** expose no broker port and no live-order capability.

### Governed production MLOps

- **FR-032 Model lifecycle:** register immutable model versions and append actor/reason/evidence
  lifecycle transitions.
- **FR-033 Promotion policy:** require configured technical gates and approval roles before an
  assigned challenger can become champion.
- **FR-034 Deployment history:** preserve shadow, canary, active, superseded, and rollback
  deployment records and predecessor lineage.
- **FR-035 Batch inference:** resolve only the scoped champion, verify the target and ordered
  feature signature, and bound batch size.
- **FR-036 Prediction ledger:** persist idempotent prediction batches before outcomes are known;
  append corrections rather than overwriting records.
- **FR-037 Outcome reconciliation:** calculate the exact versioned target, retain source-label
  lineage, and append strict outcome revisions only when evidence changes.
- **FR-038 Feedback:** calculate realized error, bias, direction, and probability-calibration
  metrics from latest outcomes in an explicit window.
- **FR-039 Monitoring:** persist distribution and performance drift evidence and create warning or
  critical alerts at configured thresholds.
- **FR-040 Retraining:** persist idempotent retraining requests and terminal success/failure state.
- **FR-041 Champion–challenger comparison:** require minimum samples, minimum improvement,
  validation evidence, and authorization before promotion.
- **FR-042 Rollback:** allow a critical alert for the current champion to restore its recorded
  predecessor through an audited registry transaction.
- **FR-043 Conservative defaults:** disable online inference and automatic promotion by default.
- **FR-044 No self-modification:** prohibit autonomous source-code mutation and permissionless
  model replacement.

### Operational platform

- **FR-045 Transactional operations:** commit paper-state, idempotency, audit, and outbox evidence atomically.
- **FR-046 Database migrations:** package versioned Alembic migrations and prohibit ad hoc managed schema creation.
- **FR-047 Audit integrity:** retain ordered, attributed, hash-chained audit evidence and verify it independently.
- **FR-048 Event delivery:** publish integration events through a durable transactional outbox with retry and replay evidence.
- **FR-049 Authenticated API:** provide versioned, schema-validated endpoints with JWT verification and server-side role enforcement.
- **FR-050 Paper operations:** provide account and paper-order workflows with exact accounting, freshness checks, risk limits, and idempotency.
- **FR-051 Abuse controls:** enforce trusted hosts, request limits, bounded rate limiting, pagination bounds, and sanitized problem responses.
- **FR-052 Observability:** provide low-cardinality metrics, traces, health checks, and immutable SLO snapshots.
- **FR-053 Supply-chain security:** scan source, dependencies, secrets, configuration, containers, and attest release artifacts.

### Delivery requirements

- **FR-054 Quality automation:** provide formatting, linting, strict typing, unit/integration/
  architecture tests, branch coverage, dependency auditing, builds, and CI workflows.
- **FR-055 Installability:** build and install a typed wheel from a clean checkout.

## 4. Non-goals for this release

- Licensed production market-data connectors
- Distributed/cloud persistence adapters for every high-volume research repository
- Fundamentals, macroeconomic, news, or sentiment normalization
- Public consumer API or consumer-facing dashboard
- Fully automated production promotion without governed policy
- Arbitrary user-supplied model code
- Short selling, leverage, borrow modeling, or intraday order-book simulation
- Broker connectivity or live execution
- Personalized investment recommendations or guaranteed outcomes

## 5. Success measures

- All quality gates pass from a clean checkout.
- No domain module imports a third-party framework.
- Every data, model, deployment, prediction, outcome, feedback, alert, retraining, promotion, and
  rollback record is traceable to immutable evidence.
- Future observations cannot enter features, folds, labels, simulated execution, or historical
  predictions.
- Every declared baseline completes before the run can produce a selected model.
- The final holdout is evaluated only after candidate selection.
- Paper simulations include explicit transaction costs and risk limits.
- Equivalent economic inputs yield identical content fingerprints.
- A model cannot become champion without the configured gates and authorization.
- Historical predictions and outcomes cannot be silently rewritten.
- Critical production degradation has a tested rollback path.
- Operational writes are atomic, audited, idempotent, and recoverable through the outbox.
- Authenticated API access is role controlled and rejects unsafe managed-runtime settings.
- Health, telemetry, and SLO evidence identify operational degradation without leaking secrets.
- The package builds and installs as a wheel.
