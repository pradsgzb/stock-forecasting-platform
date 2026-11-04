# Sections 16–20 Engineering Specification

## Purpose

Sections 16–20 turn approved research artifacts into a controlled production-MLOps loop. They
add model lifecycle governance, batch-first serving, immutable prediction and outcome evidence,
realized-performance feedback, drift detection, controlled retraining, champion–challenger
comparison, promotion, and rollback.

These sections do **not** add broker connectivity, order routing, self-modifying source code,
or permissionless model replacement. Live trading remains prohibited.

## Section 16 — Governed model registry

The registry is append-only and optimistic-concurrency controlled. Every model version records:

- training-run, artifact, model-card, target, task, and deployment-scope lineage;
- candidate, validation-failed, validated, staging, challenger, champion, degraded,
  rolled-back, retired, and archived lifecycle states;
- immutable lifecycle transitions with actor, reason, timestamp, and evidence references;
- champion and challenger aliases scoped by environment, target, and learning task;
- shadow, canary, and active deployment history;
- required technical gates and model-validator, risk-owner, and deployment-approver decisions.

Alias changes, lifecycle mutations, and deployment changes are committed atomically by the
repository port. A model cannot become champion unless it is the assigned challenger and its
promotion evidence satisfies the configured policy.

## Section 17 — Batch inference and prediction ledger

Inference is batch-first and resolves only the current champion for the requested deployment
scope. Before deserialization or prediction, it verifies the target and ordered feature
signature. Every request has an idempotency key and deterministic request fingerprint.

Each prediction permanently records:

- model, artifact, signature, target, and feature-set lineage;
- feature snapshot and exact input fingerprint;
- instrument, as-of date, decision cutoff, generation time, and prediction horizon;
- predicted value, optional positive-class probability, confidence, rank, interval, and
  expected volatility;
- immutable batch status and explicit per-instrument failures.

Predictions are never overwritten after outcomes become available. Corrections are new records
that preserve immutable business identity and reference the original prediction.

## Section 18 — Outcomes and feedback

The outcome collector waits for the configured target horizon, calculates the same versioned
label contract used during training, and links it to the original prediction. Provider or
source corrections create strict outcome revisions; unchanged source-label fingerprints do not
create duplicates.

Feedback aggregates the latest outcome revision per prediction and reports:

- MAE, RMSE, and bias;
- directional accuracy when direction evidence exists;
- Brier score when probability predictions exist;
- exact feedback window, sample count, model version, target key, and outcome fingerprints.

Missing, immature, conflicting, or target-mismatched outcomes remain explicit failures rather
than being converted to zero or silently discarded.

## Section 19 — Controlled continuous training

Retraining requests are durable, idempotent state machines with scheduled, new-outcome, drift,
performance, regime-change, and manual triggers. A run:

1. freezes its evidence and enters `RUNNING`;
2. invokes the existing leakage-safe training pipeline;
3. registers a candidate and evaluates promotion gates;
4. deploys an accepted candidate as a shadow/canary challenger;
5. records a terminal success or failure with model lineage.

Champion–challenger comparison requires the configured outcome count and minimum metric
improvement. Promotion is human-gated by default. Policy-based automatic promotion exists only
behind an explicit disabled-by-default setting and still requires the same validation evidence.
A critical monitoring alert can atomically roll back the champion and restore the last known
active champion through an audited registry release.

## Section 20 — Drift and production monitoring

Monitoring produces immutable reports for feature, prediction, data-quality, and performance
drift. Distribution evidence includes:

- population stability index;
- Jensen–Shannon divergence;
- standardized mean shift;
- missing-rate delta.

Realized-performance monitoring compares current and baseline feedback for error, calibration,
bias, and directional accuracy. Configured warning and critical thresholds create append-only
alerts with evidence references suitable for operational runbooks and retraining triggers.

## Safety boundary

The production loop may retrain and evaluate candidates, but it must not:

- rewrite its own source code;
- mutate historical predictions or outcomes;
- promote an unvalidated model;
- bypass approval, minimum-sample, or improvement rules;
- interpret drift alone as proof that a new model is better;
- place, route, or approve a live trade;
- claim guaranteed predictive or financial performance.
