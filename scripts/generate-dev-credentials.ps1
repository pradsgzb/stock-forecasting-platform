$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
uv run --locked python scripts/generate-dev-credentials.py @args
