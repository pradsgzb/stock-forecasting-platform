# Sections 26–31 Implementation Report

## Delivery status

This repository completes the planned Sections 00–31 foundation for a production-oriented stock
forecasting research and MLOps platform. Sections 26–31 add continuous integration, controlled
software delivery, continuous-training qualification, container and infrastructure references,
operational documentation, a structured learning framework, and an executable end-to-end reference
scenario.

The package version is `0.6.0`.

The platform remains intentionally limited to education, research, model inference, governed model
operations, and paper evaluation. It does not implement broker connectivity, live order routing,
margin trading, short selling, or autonomous capital deployment.

| Section | Delivered capability | Primary locations |
|---|---|---|
| 26 | Locked CI, multi-platform tests, security gates, coverage, package evidence | `.github/workflows/ci.yml`, `scripts/check.*`, `scripts/release-check.*` |
| 27 | Immutable release evidence, protected promotion, rollback, CT qualification | `.github/workflows/delivery.yml`, `.github/workflows/continuous-training.yml`, `application/delivery/` |
| 28 | Docker, Compose, Kubernetes, GCP/Azure Terraform references, validation | `compose.yaml`, `deploy/`, `infra/`, `scripts/validate-*` |
| 29 | Setup, run, debug, deployment, governance, and incident documentation | `docs/operations/`, `docs/governance/` |
| 30 | Versioned student learning catalog and guided extension exercises | `domain/learning/`, `application/learning/`, `labs/` |
| 31 | Deterministic ingestion-to-rollback reference scenario | `reference/service.py`, `scripts/run-reference-scenario.*` |

## Section 26 — Continuous integration

The CI foundation now provides:

- dependency installation exclusively from a reviewed `uv.lock` in CI and release workflows;
- Python 3.13 and 3.14 compatibility coverage;
- Linux, Windows, and macOS test execution;
- Ruff formatting and lint checks;
- strict Pyright analysis;
- Bandit security linting;
- branch-aware Pytest coverage with a 90% floor;
- deterministic reference-scenario execution;
- repository and deployment-reference validation;
- package, JUnit, coverage, and verification evidence;
- CodeQL, dependency-review, secret/configuration scanning, container scanning, SBOM, and
  provenance provisions.

The local bootstrap path may create the resolver-owned lockfile once when it is missing. CI,
containers, and releases never synthesize or silently update a lockfile.

## Section 27 — Controlled delivery and continuous training

### Release evidence

The delivery domain introduces immutable, content-derived records for:

- release artifact names, media types, SHA-256 digests, sizes, and evidence references;
- source-tree and Git revision identity;
- required and observed quality gates;
- release environment and build-run identity;
- promotion plans with source and target environments;
- explicit production approval evidence;
- release-manifest verification after serialization.

Malformed manifest types, missing gates, changed fingerprints, non-adjacent promotions, and
unapproved production plans are rejected.

### Delivery workflow

The controlled GitHub delivery workflow:

1. checks out an exact revision;
2. installs the reviewed dependency graph;
3. executes release checks and repository validation;
4. builds wheel, source distribution, SBOM, deployment bundle, and container image;
5. resolves and records an immutable image digest;
6. produces a release manifest and promotion plan;
7. retains and attests evidence; and
8. optionally deploys through a protected environment.

Kubernetes delivery pins the API, worker, and migration Job to the same image digest. The migration
Job completes before workload rollout. Rollback requires a previously approved immutable digest.

### Continuous-training qualification

The continuous-training workflow runs deterministic scheduled or manually requested qualification.
It does not automatically promote a model. Existing model-registry evidence, minimum-sample rules,
human approval, monitoring, and rollback controls remain authoritative.

## Section 28 — Containers and infrastructure as code

### Local containers

`compose.yaml` provides:

- PostgreSQL;
- a migration service;
- authenticated API service;
- outbox worker;
- optional MinIO and MLflow services under the `mlops` profile;
- optional Prometheus and Grafana services under the `observability` profile; and
- a `debugpy` API service under the `debug` profile.

`Dockerfile` remains the production image definition. `Dockerfile.debug` adds only the tooling
required for an isolated development debugger.

### Kubernetes

The Kubernetes configuration includes:

- namespace and service account;
- non-secret runtime configuration;
- API and worker Deployments;
- migration Job;
- Service, PodDisruptionBudget, HorizontalPodAutoscaler, and network policies;
- integration, staging, and production overlays;
- immutable image rendering and validation scripts;
- migration-first rollout and bounded rollout waits.

Runtime secrets are intentionally absent from the repository. They must be provisioned through an
approved external secret mechanism or platform process.

### Terraform references

Cloud-neutral product code is accompanied by GCP and Azure reference modules. They cover the
principal network, identity, private data-service, container-registry, secret, observability,
backup, and compute boundaries. The modules require organization-specific review and values before
use. No cloud credential or deployable secret is embedded in source control.

### Repository validation

`scripts/validate-repository.py` validates:

- required source and operational files;
- TOML, JSON, YAML, and Python syntax;
- Markdown link targets;
- full-SHA GitHub Action pinning;
- Kustomize resource references;
- Terraform version declarations, delimiter structure, and obvious secret-policy violations; and
- optional native Docker, Kubernetes, and Terraform checks when their executables are available.

## Section 29 — Documentation, governance, and runbooks

The repository now contains task-oriented documentation for:

- [workstation and Docker setup](docs/operations/setup.md);
- [normal execution and service operation](docs/operations/running.md);
- [VS Code, `debugpy`, Pytest, API, database, and model debugging](docs/operations/debugging.md);
- [controlled delivery, promotion, and rollback](docs/operations/deployment.md);
- [continuous-training operation](docs/operations/continuous-training.md);
- [dependency locking](docs/operations/dependency-lock.md); and
- [incident and recovery runbooks](docs/operations/runbooks/README.md).

Governance templates cover experiment registration, model cards, release readiness, and model
promotion. Runbooks cover provider outages, data corrections, training and prediction failures,
model degradation, database failure, secret exposure, failed deployments, and disaster recovery.

## Section 30 — Student learning framework

A machine-readable, versioned exercise catalog now supplies:

- stable exercise identifiers;
- learning tracks and difficulty levels;
- prerequisites and dependency-graph validation;
- objectives, deliverables, acceptance criteria, suggested reading, and reflection prompts;
- extension points that preserve the production architecture; and
- CLI commands for listing, inspecting, and validating exercises.

The included tracks cover Python engineering, data engineering, classical ML, time-series and deep
learning, financial modeling, MLOps, cloud/DevOps, and research methodology. Learning tasks are
isolated from production behavior; the main repository remains executable and tested.

## Section 31 — End-to-end reference scenario

The deterministic reference scenario demonstrates one complete vertical slice using synthetic
end-of-day equity data:

1. create exchange and instrument identity;
2. ingest immutable provider pages;
3. validate and normalize point-in-time observations;
4. materialize versioned features;
5. generate a future-return target and immutable dataset;
6. create leakage-safe walk-forward partitions and a final holdout;
7. train mandatory baselines and a candidate model;
8. evaluate predictive evidence and execute a cost-aware paper backtest;
9. register, validate, approve, stage, and promote a champion;
10. generate immutable predictions;
11. collect realized outcomes and feedback;
12. produce monitoring evidence;
13. trigger and qualify a challenger;
14. promote the challenger through the governed path; and
15. inject a critical condition and prove rollback to the prior champion.

The scenario produces a machine-readable JSON report with content fingerprints and model IDs. It
uses fixed synthetic inputs and deterministic timestamps for repeatable qualification.

## Setup, run, and debug entry points

### Setup

```bash
./scripts/bootstrap.sh
cp .env.example .env
./scripts/generate-dev-credentials.sh
export SP_API__JWT_VERIFICATION_KEY_PATH=.local/secrets/jwt-public.pem
uv run --locked stock-predictor db-upgrade
uv run --locked stock-predictor doctor
```

Windows equivalents are provided in `docs/operations/setup.md` and the matching PowerShell
scripts.

### Run

```bash
uv run --locked stock-predictor serve
./scripts/run-reference-scenario.sh
./scripts/dev-up.sh
```

### Debug

```bash
./scripts/debug-api.sh
uv run --locked pytest tests/path/test_file.py::test_name -vv -s --pdb
```

The repository includes VS Code launch and task configurations for the API, reference scenario,
current test file, and Docker debugger attachment.

## Safety and scope controls

The completed platform preserves these non-negotiable controls:

- no broker adapter or live-order interface;
- live trading disabled and rejected by typed configuration;
- paper-only portfolio and backtesting behavior;
- human-gated model promotion by default;
- online inference disabled by default;
- trusted model deserialization disabled by default;
- immutable predictions and append-only outcome corrections;
- point-in-time data availability and feature lineage;
- explicit release evidence and immutable software image references;
- external secret management for deployed environments.

## Production adoption boundary

The repository is a comprehensive engineering foundation, not a guarantee of predictive accuracy,
profitability, cloud compliance, or production readiness for a particular organization. A real
deployment still requires licensed market data, organization-specific cloud and network review,
identity integration, threat modeling, load testing, disaster-recovery exercises, cost modeling,
security assessment, legal review, and operating approval.
