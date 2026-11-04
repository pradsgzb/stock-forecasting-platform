#!/usr/bin/env bash
set -Eeuo pipefail

command -v uv >/dev/null 2>&1 || {
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
}

if [[ ! -f uv.lock ]]; then
  echo "uv.lock is absent; resolving dependencies for this workstation."
  echo "Review and commit the generated lockfile before CI, container, or release use."
  uv lock --python 3.13
fi

uv lock --check
uv sync --locked --all-groups
uv run --locked pre-commit install --install-hooks
uv run --locked stock-predictor doctor
