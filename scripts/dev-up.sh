#!/usr/bin/env bash
set -Eeuo pipefail

[[ -f .env ]] || {
  echo "Create .env from .env.example before starting the local platform." >&2
  exit 1
}
[[ -f .local/secrets/jwt-public.pem ]] || ./scripts/generate-dev-credentials.sh

docker compose up --build --detach postgres migrate api worker
curl --fail --retry 20 --retry-delay 2 http://127.0.0.1:"${API_PORT:-8080}"/health/ready
echo
echo "API ready at http://127.0.0.1:${API_PORT:-8080}"
