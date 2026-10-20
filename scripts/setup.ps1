<#
.SYNOPSIS
  One-time RescueBridge setup (project-scoped). Installs pinned Python deps into .venv with uv and builds
  the web app. Does not need administrator rights, does not change system settings, firewall, startup items
  or trust stores, and does not download language models.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
[CmdletBinding()]
param([switch]$SkipWeb)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$timings = [ordered]@{}
$sw = [Diagnostics.Stopwatch]::StartNew()

function Step($name, [scriptblock]$block) {
  Write-Host "==> $name" -ForegroundColor Cyan
  $t = [Diagnostics.Stopwatch]::StartNew()
  & $block
  if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
  $timings[$name] = [math]::Round($t.Elapsed.TotalSeconds, 1)
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "uv not found. Install it from https://docs.astral.sh/uv/ (user-level install), then re-run."
}
Step "python deps (uv sync --frozen)" { uv sync --frozen --python 3.13 }
if (-not $SkipWeb) {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js/npm not found (needed once to build the web app)." }
  Step "web deps (npm ci)" { Push-Location web; try { npm ci --no-audit --no-fund } finally { Pop-Location } }
  Step "web build" { Push-Location web; try { npm run build } finally { Pop-Location } }
}
Step "doctor (read-only)" { & .venv\Scripts\python.exe -m rescuebridge.cli doctor; $global:LASTEXITCODE = 0 }
$timings["total_seconds"] = [math]::Round($sw.Elapsed.TotalSeconds, 1)
New-Item -ItemType Directory -Force evidence | Out-Null
$out = "evidence\setup_timing_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$timings | ConvertTo-Json | Set-Content -Encoding utf8 $out
Write-Host "Setup finished in $($timings['total_seconds']) s. Timing evidence: $out" -ForegroundColor Green
Write-Host "Next: powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
