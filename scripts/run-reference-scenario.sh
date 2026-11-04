#!/usr/bin/env bash
set -Eeuo pipefail

WORKSPACE="${1:-.local/reference-scenario}"
OUTPUT="${2:-${WORKSPACE}/report.json}"
mkdir -p "$(dirname "${OUTPUT}")"
uv run --locked stock-predictor reference-scenario --workspace "${WORKSPACE}" --output "${OUTPUT}"
echo "Reference scenario report: ${OUTPUT}"
