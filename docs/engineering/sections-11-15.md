# Sections 11–15 Engineering Specification

## Purpose

Sections 11–15 convert the point-in-time market-data and feature foundation into a controlled
supervised-learning and paper-backtesting platform. They do not provide model deployment,
continuous training, prediction serving, broker connectivity, or live trading.

## Section 11 — Targets, labels, datasets, and time splits

The platform provides versioned targets for:

- future simple and logarithmic return;
- positive-return classification;
- realized volatility;
- relative return against an explicit benchmark;
- cross-sectional percentile rank;
- maximum adverse and favorable excursion.

Every label records the instrument, as-of date, horizon end, outcome cutoff, actual
availability time, source bars, target version, and deterministic fingerprint. Relative labels
retain target and benchmark lineage. Cross-sectional ranks inherit the peer group’s latest
availability and complete peer-source lineage.

Dataset snapshots are immutable, content-addressed collections of numeric rows. Their content
fingerprint is independent of publication time and generated identifiers. A row proves that its
label became available only after its feature decision cutoff.

Time splitting uses expanding or rolling walk-forward folds with configurable gaps, purging of
label overlap, embargo periods, and a final untouched holdout.

## Section 12 — Model plugin SDK and baselines

A model plugin declares a stable key and supported learning tasks. Fitted models expose one
common contract for prediction, positive-class probability, feature importance, health checks,
and trusted serialization.

Mandatory reference implementations include:

- zero-return regression baseline;
- historical-mean regression baseline;
- declared-feature echo baseline for momentum, market, or sector comparisons;
- majority-probability classification baseline;
- ridge regression;
- logistic regression;
- random-forest regression and classification.

An advanced candidate cannot complete selection unless every baseline declared by the training
request is also a candidate and completes successfully.

## Section 13 — Training and experiment evidence

Training is divided into two strict stages:

1. candidate evaluation on development walk-forward folds;
2. one final evaluation of the selected candidate on the untouched holdout.

The pipeline records append-only experiment events for startup, completed or failed trials,
selection, holdout evaluation, artifact creation, completion, and failure. Candidate search is
bounded and deterministic under its recorded seed.

Artifacts are checksummed and serialized behind a codec port. Deserialization of Python/joblib
artifacts is disabled unless the operator explicitly enables the trusted-artifact boundary.
Every completed model receives a model card containing intended use, prohibited uses, lineage,
validation score, holdout score, and limitations.

## Section 14 — Evaluation, calibration, explainability, and robustness

Regression evaluation includes MAE, RMSE, median absolute error, R-squared, directional
accuracy, Spearman rank correlation, and information coefficient. Binary evaluation includes
balanced accuracy, precision, recall, ROC-AUC, log loss, and Brier score.

The evaluation service can additionally produce:

- bootstrap confidence intervals;
- calibration bins;
- slice reports by supplied cohort;
- permutation importance;
- native model importance when available.

All reports are immutable and content-addressed. Explainability is evidence about model
behavior; it is never represented as causation.

## Section 15 — Paper backtesting and risk

The backtester is explicitly paper-only. It has no broker port and no live-order capability.
Signals may execute no earlier than the next session open and only when generated before that
open. The engine supports:

- long-only top-k portfolio construction;
- position, gross-exposure, turnover, volume-participation, and drawdown limits;
- commission, spread, slippage, and fixed cost assumptions;
- partial fills caused by volume or cash limits;
- liquidation on the session after a risk halt;
- benchmark total return, active return, and tracking error;
- deterministic result fingerprints independent of generated run/order/fill identifiers.

The engine reports return, annualized return and volatility, Sharpe and Sortino ratios,
maximum drawdown, hit rate, profit factor, turnover, transaction costs, commissions, trade
count, and ending equity.

## Safety boundary

These sections remain research infrastructure. They must not:

- recommend a security to a consumer;
- claim profitable or guaranteed performance;
- connect to a broker;
- place, route, or approve a live order;
- promote a model to production;
- retrain or replace a deployed model automatically.
