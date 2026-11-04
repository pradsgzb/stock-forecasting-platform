$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not (Test-Path -LiteralPath ".local/secrets/jwt-public.pem" -PathType Leaf)) {
    ./scripts/generate-dev-credentials.ps1
}
if (-not $env:SP_API__JWT_VERIFICATION_KEY_PATH) {
    $env:SP_API__JWT_VERIFICATION_KEY_PATH = ".local/secrets/jwt-public.pem"
}
$listen = if ($env:DEBUG_LISTEN) { $env:DEBUG_LISTEN } else { "127.0.0.1:5678" }
uv run --locked python -m debugpy --listen $listen --wait-for-client -m stock_predictor.cli serve
