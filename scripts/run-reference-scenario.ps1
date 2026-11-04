param(
    [string]$Workspace = ".local/reference-scenario",
    [string]$Output = ""
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not $Output) {
    $Output = Join-Path $Workspace "report.json"
}
$parent = Split-Path -Parent $Output
if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}
uv run --locked stock-predictor reference-scenario --workspace $Workspace --output $Output
Write-Host "Reference scenario report: $Output"
