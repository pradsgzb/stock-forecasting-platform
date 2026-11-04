#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ! -f uv.lock ]]; then
  echo "release check failed: uv.lock is required; see docs/operations/dependency-lock.md" >&2
  exit 1
fi

uv lock --check
uv sync --locked --all-groups
mkdir -p .local
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
uv run --locked bandit -q -r src -ll
uv run --locked pytest \
  --cov=stock_predictor \
  --cov-report=term-missing \
  --cov-report=xml \
  --junitxml=.local/test-results.xml
uv export --locked --all-groups --no-hashes --output-file .local/audit-requirements.txt
uv run --locked pip-audit --requirement .local/audit-requirements.txt
uv run --locked python scripts/validate-repository.py
uv run --locked stock-predictor reference-scenario \
  --workspace .local/reference-scenario-release \
  --output .local/reference-scenario-release/report.json
uv build --locked
