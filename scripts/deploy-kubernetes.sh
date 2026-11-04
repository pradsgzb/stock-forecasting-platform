#!/usr/bin/env bash
set -Eeuo pipefail

USAGE="deploy-kubernetes.sh <integration|staging|production> \
<image@sha256:digest> [--skip-migration]"
TARGET="${1:?Usage: ${USAGE}}"
IMAGE="${2:?Usage: ${USAGE}}"
MODE="${3:-}"
case "${TARGET}" in
  integration|staging|production) ;;
  *) echo "Unsupported target: ${TARGET}" >&2; exit 2 ;;
esac
case "${MODE}" in
  ""|--skip-migration) ;;
  *) echo "Unsupported option: ${MODE}" >&2; exit 2 ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
uv run --locked python scripts/render-kubernetes.py \
  --overlay "deploy/kubernetes/overlays/${TARGET}" \
  --image "${IMAGE}" \
  --prerequisite-output "${WORK}/prerequisites.yaml" \
  --migration-output "${WORK}/migration.yaml" \
  --output "${WORK}/workloads.yaml"

kubectl auth can-i create namespaces >/dev/null
kubectl auth can-i create jobs --namespace stock-forecasting >/dev/null
kubectl auth can-i patch deployments --namespace stock-forecasting >/dev/null

# Establish the namespace before applying any namespaced prerequisite resources.
kubectl apply --server-side --field-manager=stock-predictor-delivery \
  -f deploy/kubernetes/base/namespace.yaml
kubectl wait --for=jsonpath='{.status.phase}'=Active namespace/stock-forecasting --timeout=60s
kubectl apply --server-side --field-manager=stock-predictor-delivery \
  -f "${WORK}/prerequisites.yaml"

# Runtime identity and database secrets are provisioned outside this repository.
kubectl get secret stock-predictor-runtime-secrets --namespace stock-forecasting >/dev/null
kubectl get secret stock-predictor-identity --namespace stock-forecasting >/dev/null

if [[ "${MODE}" != "--skip-migration" ]]; then
  kubectl delete job stock-predictor-migrate \
    --namespace stock-forecasting --ignore-not-found
  kubectl apply --server-side --field-manager=stock-predictor-delivery \
    -f "${WORK}/migration.yaml"
  kubectl wait --for=condition=complete job/stock-predictor-migrate \
    --namespace stock-forecasting --timeout=15m
fi

# Workloads are changed only after prerequisites and the forward migration succeed.
kubectl apply --server-side --field-manager=stock-predictor-delivery \
  -f "${WORK}/workloads.yaml"
kubectl rollout status deployment/stock-predictor-api \
  --namespace stock-forecasting --timeout=10m
kubectl rollout status deployment/stock-predictor-worker \
  --namespace stock-forecasting --timeout=10m
