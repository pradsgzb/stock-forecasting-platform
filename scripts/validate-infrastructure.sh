#!/usr/bin/env bash
set -Eeuo pipefail
uv run --locked python scripts/validate-repository.py --external
