param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("integration", "staging", "production")]
    [string]$Target,
    [Parameter(Mandatory = $true)]
    [string]$Image,
    [switch]$SkipMigration
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("stock-predictor-" + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $prerequisites = Join-Path $work "prerequisites.yaml"
    $workloads = Join-Path $work "workloads.yaml"
    $migration = Join-Path $work "migration.yaml"
    uv run --locked python scripts/render-kubernetes.py `
        --overlay "deploy/kubernetes/overlays/$Target" `
        --image $Image `
        --prerequisite-output $prerequisites `
        --migration-output $migration `
        --output $workloads

    kubectl auth can-i create namespaces | Out-Null
    kubectl auth can-i create jobs --namespace stock-forecasting | Out-Null
    kubectl auth can-i patch deployments --namespace stock-forecasting | Out-Null

    kubectl apply --server-side --field-manager=stock-predictor-delivery `
        -f deploy/kubernetes/base/namespace.yaml
    kubectl wait --for=jsonpath='{.status.phase}'=Active `
        namespace/stock-forecasting --timeout=60s
    kubectl apply --server-side --field-manager=stock-predictor-delivery `
        -f $prerequisites

    kubectl get secret stock-predictor-runtime-secrets `
        --namespace stock-forecasting | Out-Null
    kubectl get secret stock-predictor-identity `
        --namespace stock-forecasting | Out-Null

    if (-not $SkipMigration) {
        kubectl delete job stock-predictor-migrate `
            --namespace stock-forecasting --ignore-not-found
        kubectl apply --server-side --field-manager=stock-predictor-delivery `
            -f $migration
        kubectl wait --for=condition=complete job/stock-predictor-migrate `
            --namespace stock-forecasting --timeout=15m
    }

    kubectl apply --server-side --field-manager=stock-predictor-delivery `
        -f $workloads
    kubectl rollout status deployment/stock-predictor-api `
        --namespace stock-forecasting --timeout=10m
    kubectl rollout status deployment/stock-predictor-worker `
        --namespace stock-forecasting --timeout=10m
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
