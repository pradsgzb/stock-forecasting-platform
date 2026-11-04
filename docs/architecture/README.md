# Architecture Overview

The platform is a modular monolith with replaceable adapters and independently executable
workers to be introduced only when scaling or failure-isolation requirements justify them.
Clean/Hexagonal Architecture protects the domain from frameworks, market-data vendors, ML
libraries, persistence products, and deployment platforms.

## Dependency rule

```text
bootstrap / CLI
   ├── application ──→ ports ──→ domain
   └── adapters ─────→ ports ──→ domain
```

The arrows indicate source-code dependencies. Domain code imports only the Python standard
library and other domain modules. scikit-learn and joblib are adapter concerns.

## Why not microservices now?

Sections 00–25 introduce an independently deployable operations API and dispatcher, but do not yet present enough independently scaled workloads that require network
boundaries. Premature services would add distributed transactions, contract versioning,
observability burden, and failure modes without increasing research integrity. Modules remain
extractable when API, training, batch inference, monitoring, or continuous-training workloads
have proven scaling and ownership needs.

## Runtime composition

`stock_predictor.bootstrap.container.build_container` is the default composition root. It
constructs immutable settings, a clock, exchange catalog, provider and model registries,
storage/repository adapters, data services, target and dataset services, splitter, evaluator,
training, paper-backtesting, registry, inference, feedback, monitoring, controlled retraining,
transactional operations, health, SLO, telemetry, and outbox services. Tests may replace every dependency explicitly.

## Detailed views

- `system-context.md` — actors and external systems
- `container.md` — runtime and storage containers
- `component.md` — application, domain, port, and adapter boundaries
- `market-data-and-features.md` — Sections 06–10 data flow
- `model-development-and-backtesting.md` — Sections 11–15 research flow
- `production-mlops.md` — Sections 16–20 registry, serving, feedback, and control loop
- `operations-platform.md` — Sections 21–25 API, transactional persistence, audit, and telemetry
- `data-lineage.md` — source-to-evidence lineage
- `sequences.md` — important execution sequences
- `trust-boundaries.md` — security and integrity boundaries
- `deployment.md` — current deployment baseline and future separation points
