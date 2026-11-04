$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/"
}

if (-not (Test-Path -LiteralPath "uv.lock" -PathType Leaf)) {
    Write-Host "uv.lock is absent; resolving dependencies for this workstation."
    Write-Host "Review and commit the generated lockfile before CI, container, or release use."
    uv lock --python 3.13
}

uv lock --check
uv sync --locked --all-groups
uv run --locked pre-commit install --install-hooks
uv run --locked stock-predictor doctor
