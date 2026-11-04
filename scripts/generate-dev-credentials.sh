#!/usr/bin/env bash
set -Eeuo pipefail
uv run --locked python scripts/generate-dev-credentials.py "$@"
