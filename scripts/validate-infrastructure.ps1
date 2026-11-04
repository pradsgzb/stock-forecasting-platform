$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
uv run --locked python scripts/validate-repository.py --external
