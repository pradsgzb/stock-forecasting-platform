#!/usr/bin/env bash
set -Eeuo pipefail

[[ -f .local/secrets/jwt-public.pem ]] || ./scripts/generate-dev-credentials.sh
SP_DEFAULT_PUBLIC_KEY=".local/secrets/jwt-public.pem"
JWT_KEY_PATH="${SP_API__JWT_VERIFICATION_KEY_PATH:-${SP_DEFAULT_PUBLIC_KEY}}"
export SP_API__JWT_VERIFICATION_KEY_PATH="${JWT_KEY_PATH}"
uv run --locked python -m debugpy --listen "${DEBUG_LISTEN:-127.0.0.1:5678}" \
  --wait-for-client -m stock_predictor.cli serve
