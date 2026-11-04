# Stock Forecasting Platform

A production-oriented Python foundation for point-in-time-correct market-data research, supervised learning, cost-aware paper backtesting, governed model deployment, immutable prediction feedback, monitoring, and controlled continuous training.

**Important:** this project is for education, research, inference, and paper evaluation. It does not provide investment advice, broker integration, live order routing, margin trading, or autonomous capital deployment.

## Implemented scope

The repository implements Sections 00–31:

- engineering specification, Clean/Hexagonal Architecture, and strict Python tooling;
- instrument master, exchange calendars, provider SDK, immutable ingestion, data quality, point-in-time normalization, and features;
- targets, datasets, purged walk-forward splitting, model plugins, training, evaluation, explainability, and paper backtesting;
- governed model registry, inference ledger, realized outcomes, feedback, continuous training, drift monitoring, and rollback;
- durable operational persistence, authenticated API, paper trading, observability, security, and supply-chain controls;
- CI, controlled delivery, containers, Kubernetes, GCP/Azure Terraform references, governance, learning labs, and an executable end-to-end scenario.

## Quick setup

Prerequisites: Python 3.13 or 3.14, `uv`, and Git.

```bash
./scripts/bootstrap.sh
cp .env.example .env
./scripts/generate-dev-credentials.sh
export SP_API__JWT_VERIFICATION_KEY_PATH=.local/secrets/jwt-public.pem
uv run --locked stock-predictor db-upgrade
uv run --locked stock-predictor doctor
uv run --locked pytest -q
```

Windows PowerShell:

```powershell
./scripts/bootstrap.ps1
Copy-Item .env.example .env
./scripts/generate-dev-credentials.ps1
$env:SP_API__JWT_VERIFICATION_KEY_PATH = ".local/secrets/jwt-public.pem"
uv run --locked stock-predictor db-upgrade
uv run --locked stock-predictor doctor
uv run --locked pytest -q
```

On the first setup, the bootstrap script generates `uv.lock` when it is absent; that resolution requires package-index access. Review and commit the generated lockfile before using CI, containers, or release workflows.

Complete setup instructions: [docs/operations/setup.md](docs/operations/setup.md)

## Run

Start the native API:

```bash
uv run --locked stock-predictor serve
```

Run the complete deterministic scenario:

```bash
./scripts/run-reference-scenario.sh
```

Start PostgreSQL, migration, API, and worker with Docker:

```bash
./scripts/dev-up.sh
```

Detailed execution instructions: [docs/operations/running.md](docs/operations/running.md)

## Debug

Use the included VS Code launch configurations or start a `debugpy` listener:

```bash
./scripts/debug-api.sh
```

Debug a test:

```bash
uv run --locked pytest tests/path/test_file.py::test_name -vv -s --pdb
```

Detailed debugging instructions: [docs/operations/debugging.md](docs/operations/debugging.md)

## Quality gates

```bash
./scripts/check.sh
./scripts/release-check.sh
uv run --locked python scripts/validate-repository.py --external
```

The release gate covers formatting, linting, strict typing, security lint, branch coverage, dependency audit, package build, and repository validation. GitHub workflows add multi-platform compatibility, CodeQL, dependency review, secret/configuration scans, container scanning, artifact attestation, protected delivery, and continuous-training qualification.

## Architecture

The system uses a modular monolith with explicit domain, application, port, and adapter boundaries. Long-running and deployment concerns remain outside the domain. Important entry points:

- [Architecture index](docs/architecture/README.md)
- [Operations platform](docs/architecture/operations-platform.md)
- [Production MLOps](docs/architecture/production-mlops.md)
- [Sections 26–31](docs/engineering/sections-26-31.md)
- [Security threat model](docs/security/threat-model.md)

## Operations and deployment

- [Operations index](docs/operations/README.md)
- [Controlled deployment](docs/operations/deployment.md)
- [Continuous training](docs/operations/continuous-training.md)
- [Runbooks](docs/operations/runbooks/README.md)
- [Terraform references](infra/terraform/README.md)
- [Kubernetes manifests](deploy/kubernetes/)

## Student learning framework

```bash
uv run --locked stock-predictor labs validate
uv run --locked stock-predictor labs list
uv run --locked stock-predictor labs show model-plugin
```

See [labs/README.md](labs/README.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
