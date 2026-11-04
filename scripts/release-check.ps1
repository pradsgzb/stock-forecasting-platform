$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath "uv.lock" -PathType Leaf)) {
    throw "Release check failed: uv.lock is required; see docs/operations/dependency-lock.md"
}

uv lock --check
uv sync --locked --all-groups
New-Item -ItemType Directory -Force -Path ".local" | Out-Null
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
uv run --locked bandit -q -r src -ll
uv run --locked pytest --cov=stock_predictor --cov-report=term-missing `
    --cov-report=xml --junitxml=.local/test-results.xml
uv export --locked --all-groups --no-hashes --output-file ".local/audit-requirements.txt"
uv run --locked pip-audit --requirement ".local/audit-requirements.txt"
uv run --locked python scripts/validate-repository.py
uv run --locked stock-predictor reference-scenario `
    --workspace .local/reference-scenario-release `
    --output .local/reference-scenario-release/report.json
uv build --locked
