# Debugging guide

## Debugging principles

- Reproduce failures with synthetic or de-identified data.
- Record dataset, feature, model, and configuration fingerprints.
- Never copy production credentials, raw market-vendor secrets, or personal data into a debugger.
- Do not alter immutable predictions, outcomes, audit records, or model artifacts to make a failure disappear.
- Prefer one failing test or one bounded scenario over debugging the complete platform at once.

## Visual Studio Code

Open the repository root and install the recommended extensions. Select the interpreter under `.venv`.

Included launch configurations:

1. **API: local process** — starts the API with `.env` and the local JWT public key.
2. **Reference scenario** — debugs the entire synthetic vertical slice.
3. **Pytest: current file** — runs the open test file under `debugpy`.
4. **Attach: Docker API** — attaches to the debug container on `127.0.0.1:5678`.

Set breakpoints in `src/stock_predictor`, choose a configuration in **Run and Debug**, and start it.

On Windows, `.vscode/settings.json` may not resolve `.venv/bin/python`. Select `.venv\\Scripts\\python.exe` once through **Python: Select Interpreter**; VS Code stores the workspace choice locally.

## Command-line debugger

Run a failing test with Python's built-in debugger:

```bash
uv run --locked pytest tests/path/test_file.py::test_name -vv -s --pdb
```

Stop on the first failure:

```bash
uv run --locked pytest -x -vv --pdb
```

Debug an exception outside Pytest:

```bash
uv run --locked python -m pdb -m stock_predictor.cli reference-scenario \
  --workspace .local/debug-scenario \
  --output .local/debug-scenario/report.json
```

## `debugpy` local API

Linux/macOS:

```bash
./scripts/debug-api.sh
```

Windows PowerShell:

```powershell
./scripts/debug-api.ps1
```

The process waits for a debugger at `127.0.0.1:5678`. Attach using the included VS Code configuration.

To start immediately without waiting:

```bash
uv run --locked python -m debugpy --listen 127.0.0.1:5678 \
  -m stock_predictor.cli serve
```

Do not bind a debugger to a public interface outside an isolated development environment.

## Docker debugging

```bash
docker compose --profile debug up --build api-debug
```

Attach with **Attach: Docker API**. Source code is mounted read-only from `./src`, and the remote root is `/app`.

Useful diagnostics:

```bash
docker compose ps
docker compose logs --tail=200 api-debug
docker compose exec postgres pg_isready -U stock_app -d stock_platform
```

## Structured logs and correlation

Each API request obtains request and correlation identifiers. Include them when tracing a failure across the API, service layer, database, audit trail, and outbox. Logs intentionally exclude access tokens and sensitive payloads.

Set local log level temporarily:

```bash
SP_APP__LOG_LEVEL=DEBUG uv run --locked stock-predictor serve
```

Production settings prohibit debug mode. Do not weaken that rule to diagnose production incidents.

## Database debugging

Check the schema revision:

```bash
uv run --locked stock-predictor db-current
uv run --locked alembic history
```

Inspect SQLite locally:

```bash
sqlite3 .local/data/operations.db ".tables"
```

For PostgreSQL, connect with a read-only diagnostic identity where possible. Never edit audit, outbox, prediction, outcome, or model-registry tables directly.

## Model and data debugging

Start with these questions:

1. Was the source observation available at the decision cutoff?
2. Which immutable raw-object checksum produced the normalized record?
3. Which feature-set and target versions were used?
4. Was preprocessing fitted only on the training partition?
5. Was the final holdout untouched during selection?
6. Which model artifact checksum served the prediction?
7. Did the realized outcome mature under the same target definition?
8. Did transaction costs and next-session timing apply in the backtest?

The reference-scenario JSON report provides stable identifiers for tracing these stages.

## Common failures

- **401:** verify issuer, audience, algorithm, expiry, and public key; regenerate local tokens.
- **403:** the token lacks the required role.
- **429:** wait for the rate-limit window; do not disable the limiter to hide a load issue.
- **503 readiness:** inspect component checks and database connectivity.
- **Prediction missing:** confirm a champion exists for the exact deployment scope and target.
- **Outcome missing:** verify the horizon matured and source data is available after the outcome cutoff.
- **Model load rejected:** trusted deserialization is disabled by default; use approved artifacts only.
- **Kubernetes rollout timeout:** inspect migration Job, pod events, readiness probes, and runtime secrets before rollback.
