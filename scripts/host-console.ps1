<#
.SYNOPSIS
  Open RescueBridge's host console on THIS laptop (pair a phone, accept devices, revoke, Stop all).
  Creates a fresh one-time link (works once, expires after 10 minutes, laptop only) and opens it in the
  default browser. RescueBridge must already be running (scripts\start.ps1).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\host-console.ps1
  powershell -ExecutionPolicy Bypass -File scripts\host-console.ps1 -DataDir C:\Users\me\AppData\Local\RescueBridge-real
#>
[CmdletBinding()]
param([string]$DataDir = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Not set up yet: run scripts\setup.ps1 first." }
$data = if ($DataDir) { $DataDir } elseif ($env:RB_DATA_DIR) { $env:RB_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "RescueBridge" }
& $py -m rescuebridge.cli --data-dir $data host-console
exit $LASTEXITCODE
