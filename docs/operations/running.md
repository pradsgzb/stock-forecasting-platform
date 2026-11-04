# Running the platform

## Command overview

```bash
uv run --locked stock-predictor --help
```

Important commands:

| Command | Purpose |
|---|---|
| `doctor` | Print safe runtime configuration and configured exchanges. |
| `session` | Resolve a trading session for an exchange and date. |
| `phase` | Resolve the market phase at a UTC instant. |
| `db-upgrade` | Apply packaged database migrations. |
| `db-current` | Display the current database revision. |
| `serve` | Start the authenticated operations API. |
| `worker` | Dispatch transactional outbox events. |
| `reference-scenario` | Execute the complete deterministic Sections 00–31 scenario. |
| `labs` | List, inspect, and validate learning exercises. |
| `release-manifest` | Create, verify, and plan promotion of release evidence. |

## Native process mode

### Start the API

Generate local identity material and export its public key as described in [Setup](setup.md), then run:

```bash
uv run --locked stock-predictor db-upgrade
uv run --locked stock-predictor serve
```

Default endpoints:

- Liveness: `http://127.0.0.1:8080/health/live`
- Readiness: `http://127.0.0.1:8080/health/ready`
- OpenAPI: `http://127.0.0.1:8080/docs`
- Dashboard: `http://127.0.0.1:8080/dashboard`

The dashboard, operational API, and metrics endpoint require a bearer token. Load the local token without printing it in shell history:

```bash
TOKEN="$(cat .local/secrets/operator-token)"
curl -H "Authorization: Bearer ${TOKEN}" http://127.0.0.1:8080/api/v1/system
```

PowerShell:

```powershell
$token = (Get-Content .local/secrets/operator-token -Raw).Trim()
Invoke-RestMethod -Headers @{ Authorization = "Bearer $token" } `
    http://127.0.0.1:8080/api/v1/system
```

### Start the worker

In a second terminal:

```bash
uv run --locked stock-predictor worker --limit 100 --poll-seconds 5
```

Use `--once` in tests and operational diagnostics.

## Complete reference scenario

Linux/macOS:

```bash
./scripts/run-reference-scenario.sh
```

Windows PowerShell:

```powershell
./scripts/run-reference-scenario.ps1
```

Direct invocation:

```bash
uv run --locked stock-predictor reference-scenario \
  --workspace .local/reference-scenario \
  --output .local/reference-scenario/report.json
```

The scenario uses synthetic prices and performs ingestion, point-in-time validation, features, labels, purged splitting, model training, evaluation, paper backtesting, registry promotion, inference, realized outcomes, monitoring, retraining, and rollback. It never connects to a broker.

## Learning catalog

```bash
uv run --locked stock-predictor labs validate
uv run --locked stock-predictor labs list
uv run --locked stock-predictor labs show leakage-safe-feature
```

See [Student learning framework](../../labs/README.md).

## Docker Compose

### Base stack

```bash
./scripts/dev-up.sh
```

Stop without deleting data:

```bash
./scripts/dev-down.sh
```

Stop and remove local volumes only when data loss is intentional:

```bash
./scripts/dev-down.sh --volumes
```

### MLOps services

```bash
docker compose --profile mlops up --build --detach
```

This adds MinIO and MLflow for adapter development. The core platform remains usable without them.

### Observability

```bash
docker compose --profile observability up --build --detach
```

This adds Prometheus and Grafana. The generated local Prometheus token is mounted read-only.

### Debug container

```bash
docker compose --profile debug up --build api-debug
```

The debug process listens on port `5678`, waits for a debugger, and serves the API on host port `8081` after attachment. See [Debugging](debugging.md).

## Kubernetes rendering

Render an overlay without applying it:

```bash
kubectl kustomize deploy/kubernetes/overlays/integration
kubectl kustomize deploy/kubernetes/overlays/staging
kubectl kustomize deploy/kubernetes/overlays/production
```

Production deployment must use an immutable image reference:

```bash
./scripts/deploy-kubernetes.sh \
  staging \
  registry.example/stock-forecasting-platform@sha256:<64-hex-digest>
```

The deployment script renders the overlay, applies prerequisites, runs the migration Job, waits for completion, and only then changes and verifies the API and worker Deployments.
