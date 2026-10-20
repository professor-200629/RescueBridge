<#
.SYNOPSIS
  Lint, type-check and test. Default tests use fixture adapters and never change Windows settings.
  The windows_readonly tests READ the current user's real mouse/audio/window state without changing it.
#>
[CmdletBinding()]
param([switch]$NoReadOnlyWindows)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = ".venv\Scripts\python.exe"
$results = [ordered]@{}
function Run($name, [scriptblock]$block) {
  Write-Host "==> $name" -ForegroundColor Cyan
  & $block
  $results[$name] = if ($LASTEXITCODE -eq 0) { "pass" } else { "FAIL ($LASTEXITCODE)" }
}
Run "ruff" { & $py -m ruff check src tests }
Run "mypy" { & $py -m mypy }
$marker = if ($NoReadOnlyWindows) { @("-m", "not windows_readonly") } else { @() }
Run "pytest" { & $py -m pytest -q @marker }
Run "web typecheck" { Push-Location web; try { npm run --silent typecheck } finally { Pop-Location } }
$results.GetEnumerator() | ForEach-Object { "{0,-14} {1}" -f $_.Key, $_.Value }
if ($results.Values -match "FAIL") { exit 1 }
