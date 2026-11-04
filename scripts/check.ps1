$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

uv lock --check
uv sync --locked --all-groups
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
uv run --locked bandit -q -r src -ll
New-Item -ItemType Directory -Force -Path ".local" | Out-Null
uv run --locked pytest --cov=stock_predictor --cov-report=term-missing `
    --cov-report=xml --junitxml=.local/test-results.xml
uv run --locked python scripts/validate-repository.py
uv run --locked stock-predictor reference-scenario `
    --workspace .local/reference-scenario-check `
    --output .local/reference-scenario-check/report.json
uv build --locked
