$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not (Test-Path -LiteralPath ".env" -PathType Leaf)) {
    throw "Create .env from .env.example before starting the local platform."
}
if (-not (Test-Path -LiteralPath ".local/secrets/jwt-public.pem" -PathType Leaf)) {
    ./scripts/generate-dev-credentials.ps1
}
docker compose up --build --detach postgres migrate api worker
$port = if ($env:API_PORT) { $env:API_PORT } else { "8080" }
for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/health/ready" | Out-Null
        Write-Host "API ready at http://127.0.0.1:$port"
        exit 0
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
throw "API readiness check did not pass. Run: docker compose logs api"
