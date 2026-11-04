# Sections 06–10 Engineering Specification

## Objective

Extend the platform from stable instrument/time foundations into a deterministic, auditable
market-data and feature-engineering subsystem. The subsystem must preserve provider evidence,
make corrections visible rather than destructive, prevent future information from entering a
historical decision, and expose replacement points for data vendors and feature implementations.

## Section 06 — Market-Data Provider SDK

Delivered contracts and safeguards:

- capability declaration before a request is made;
- vendor-neutral price-bar requests and records;
- stable request fingerprints;
- opaque response pages whose exact bytes can be preserved;
- provider-owned decode boundary;
- bounded retry with exponential backoff and jitter;
- client-side sliding-window rate limiting;
- explicit transient and permanent provider errors;
- pagination and cursor-progress validation;
- deterministic synthetic provider for local development and contract tests.

A production vendor adapter must subclass `ResilientMarketDataProvider`, declare its supported
venues/frequencies/adjustments, return exact provider bytes, and decode only pages it owns.
Credentials, SDK objects, and vendor-specific fields must not enter the domain model.

## Section 07 — Immutable Raw Data and Ingestion

Delivered behavior:

- SHA-256 content-addressed storage;
- write-once publication without replacing existing objects;
- checksum and byte-count verification on every read;
- resumable per-page checkpoints;
- immutable terminal manifests;
- request-level idempotency;
- page-count and payload-size limits;
- durable local JSON catalog with atomic replacement for checkpoints;
- complete source lineage from page to normalized record.

The local adapters are suitable for development and deterministic testing. Production object
storage must preserve the same ports while adding cloud retention, object lock, encryption,
replication, lifecycle, and access-policy controls.

## Section 08 — Validation, Reconciliation, and Quality Scoring

Delivered deterministic rules:

- request conformance;
- positive and internally consistent OHLC values;
- non-negative volume;
- provider-record and natural-key uniqueness;
- exchange-session consistency;
- processing timeliness;
- deterministic record ordering;
- page-level and manifest-level record-count reconciliation;
- schema-decode failure capture.

Every run produces an immutable `ValidationReport` with findings, exact score, reconciliation,
rule-set version, status, and fingerprint. Statuses are:

- `passed`;
- `passed_with_warnings`;
- `quarantined`;
- `rejected`.

Only accepted batches may enter normalization. Rules never silently repair provider data.

## Section 09 — Point-in-Time Normalization

Delivered behavior:

- provider symbols resolve through the effective-dated instrument master;
- normalized bar identities are deterministic;
- raw observations remain append-only revisions;
- corrections must strictly increase provider revision and supersede the current revision;
- deletions are represented as tombstones;
- point-in-time queries select only revisions available at the requested cutoff;
- corporate-action adjustment factors are separately versioned and applied as derived views;
- raw values are never overwritten by an adjusted representation;
- source digest, page, row, provider record, and information timeline remain attached.

The governing temporal rule is: an input can be used only when its processing/normalization
instant and all applicable adjustment-factor processing instants are no later than the decision
cutoff.

## Section 10 — Versioned Feature Engineering

Delivered framework:

- immutable feature definitions and feature sets;
- versioned calculator strategies;
- declared lookback and minimum-history contracts;
- explicit value types and missing-value policies;
- one point-in-time calculation path for training and serving;
- source-bar lineage on every observation;
- content-based input fingerprints;
- optional materialization through a feature-store port;
- deterministic cache identity;
- contract checks preventing calculators from using undeclared bars.

Reference calculators:

- adjusted close;
- simple return;
- simple moving average;
- realized volatility;
- volume ratio.

## Explicit Non-Scope

Sections 06–10 do not provide:

- licensed production-vendor connectors;
- a distributed rate limiter;
- a cloud object-store adapter;
- a production relational/lakehouse persistence adapter;
- fundamentals, news, or macroeconomic normalization;
- labels or training datasets;
- model training, evaluation, backtesting, inference, or feedback-loop promotion;
- broker connectivity or order execution.

These exclusions are deliberate. The delivered ports and domain contracts are the extension
points for later sections.

## Definition of Done

The sections are complete when:

1. raw bytes can be fetched, persisted, resumed, and verified;
2. invalid data cannot pass the quality gate;
3. accepted records resolve to stable instruments;
4. corrections and tombstones remain reconstructable at historical cutoffs;
5. feature materialization cannot consume data beyond its decision boundary;
6. source-to-feature lineage is queryable and fingerprinted;
7. the complete test suite satisfies the existing branch-coverage threshold;
8. architecture boundaries remain executable tests;
9. documentation and composition-root wiring match the implementation.
