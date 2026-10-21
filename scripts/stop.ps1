<#
.SYNOPSIS
  Stop RescueBridge processes started by start.ps1. Only processes whose PID files RescueBridge wrote AND
  whose command line is a RescueBridge command are stopped; nothing else is touched.
#>
[CmdletBinding()]
param([string]$DataDir = "")
$ErrorActionPreference = "Stop"
$data = if ($DataDir) { $DataDir } elseif ($env:RB_DATA_DIR) { $env:RB_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "RescueBridge" }
foreach ($pidFile in @("backend.pid", "helper.pid")) {
  $path = Join-Path $data $pidFile
  if (-not (Test-Path $path)) { Write-Host "${pidFile}: not running"; continue }
  $procId = [int](Get-Content $path)
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -match "rescuebridge\.cli") {
    Stop-Process -Id $procId -Force
    Write-Host "stopped $pidFile (pid $procId)"
  } else {
    Write-Host "${pidFile}: pid $procId is not a RescueBridge process (stale file); left alone"
  }
  Remove-Item $path -Force -ErrorAction SilentlyContinue
}
# USB phone mode: drop the adb reverse mapping if a phone is still plugged in (silent when there is none).
$py = Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe"
if (Test-Path $py) {
  $usbOut = & $py -m rescuebridge.cli --data-dir $data usb-link --remove
  if ($usbOut -match "removed|error") { Write-Host $usbOut }
}
$arming = Join-Path $data "lab\arming.json"
if (Test-Path $arming) {
  $rec = Get-Content $arming -Raw | ConvertFrom-Json
  if (-not $rec.disarmed_at) {
    Write-Warning "The live lab record is not disarmed. Run: .venv\Scripts\python.exe -m rescuebridge.cli lab restore"
  }
}
