<#
.SYNOPSIS
  Start RescueBridge for the current Windows user: the helper (unless -Fixture) and the backend
  (browser app + loopback MCP server), then open the one-time host-console link on this laptop.
.PARAMETER Lan
  Also serve HTTPS on this laptop's Wi-Fi address so a paired phone can connect. Windows may ask whether
  to allow Python on the network: that choice is yours (choose Private networks only). RescueBridge never
  edits firewall rules, installs certificates, or adds startup items.
.PARAMETER Usb
  Phone plugged in by USB cable with USB debugging on: keeps an `adb reverse` mapping so the phone's own
  http://127.0.0.1:8740 reaches this laptop. Nothing listens on Wi-Fi and no firewall prompt appears. Needs
  adb (Android platform-tools) that you installed; RescueBridge never downloads it.
.PARAMETER Fixture
  Simulation only: no real Windows state is read or changed. -Scenario picks the simulated faults.
.PARAMETER Provider
  rules (keyword interpreter, default) or ollama (local model; see -Model).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Lan -Provider ollama -Model qwen2.5:3b-instruct
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Fixture -Scenario interview
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Fixture -Scenario interview -Usb
.NOTES
  The backend and helper run without windows; their output goes to <data dir>\logs (overwritten on each
  start; no tokens or pairing codes are written there). Stop them with scripts\stop.ps1.
#>
[CmdletBinding()]
param(
  [switch]$Lan,
  [switch]$Usb,
  [switch]$Fixture,
  [string]$Scenario = "healthy",
  [ValidateSet("rules", "ollama", "ollama-tools")][string]$Provider = "rules",
  [string]$Model = "qwen2.5:3b-instruct",
  [string]$DataDir = "",
  [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Not set up yet: run scripts\setup.ps1 first." }
$data = if ($DataDir) { $DataDir } elseif ($env:RB_DATA_DIR) { $env:RB_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "RescueBridge" }
New-Item -ItemType Directory -Force $data | Out-Null
$logs = Join-Path $data "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$common = @("-m", "rescuebridge.cli", "--data-dir", $data)

function Start-Logged([string]$name, [string[]]$subcommand) {
  # The process writes its own log (--log-file). Start-Process -Redirect* would make it inherit this script's
  # output handles, so anyone capturing start.ps1's output would wait until the backend exits.
  $argv = $common + @("--log-file", (Join-Path $logs "$name.log")) + $subcommand
  # Windows PowerShell joins -ArgumentList with spaces, so quote anything that contains one.
  $quoted = $argv | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
  Start-Process -FilePath $py -ArgumentList $quoted -WindowStyle Hidden | Out-Null
}

foreach ($pidFile in @("helper.pid", "backend.pid")) {
  $p = Join-Path $data $pidFile
  if (Test-Path $p) {
    $old = Get-Process -Id ([int](Get-Content $p)) -ErrorAction SilentlyContinue
    if ($old) { throw "RescueBridge already running (pid $($old.Id)). Run scripts\stop.ps1 first." }
    Remove-Item $p -Force
  }
}

if (-not $Fixture) {
  Write-Host "Starting Windows helper (current user, named pipe)..." -ForegroundColor Cyan
  Start-Logged "helper" @("helper")
  $deadline = (Get-Date).AddSeconds(15)
  while (-not (Test-Path (Join-Path $data "helper.pid"))) {
    if ((Get-Date) -gt $deadline) { throw "Helper did not start. See $(Join-Path $logs 'helper.log')" }
    Start-Sleep -Milliseconds 300
  }
}

$serveArgs = @("serve", "--provider", $Provider, "--model", $Model)
if ($Lan) { $serveArgs += "--lan" }
if ($Usb) { $serveArgs += "--usb" }
if ($Fixture) { $serveArgs += @("--fixture", "--fixture-scenario", $Scenario) }
Write-Host "Starting backend ($(if ($Fixture) {'FIXTURE SIMULATION'} else {'Real Windows'}), language: $Provider)..." -ForegroundColor Cyan
Start-Logged "backend" $serveArgs
$deadline = (Get-Date).AddSeconds(30)
while ($true) {
  try { Invoke-RestMethod -Uri "http://127.0.0.1:8740/api/health" -TimeoutSec 2 | Out-Null; break } catch {}
  if ((Get-Date) -gt $deadline) { throw "Backend did not become healthy. See $(Join-Path $logs 'backend.log')" }
  Start-Sleep -Milliseconds 400
}
if ($Usb) {
  Write-Host "Linking the phone over USB (adb reverse) and checking from the phone's side..." -ForegroundColor Cyan
  & $py @common usb-link
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Phone not linked yet. Fix the item above; the host console re-checks every 10 s while it is open."
  }
}
$link = (Get-Content (Join-Path $data "host_link.txt") -Raw).Trim()
if ($NoBrowser) {
  Write-Host "Host console link written to $(Join-Path $data 'host_link.txt') (one-time, 10 minutes)." -ForegroundColor Green
} else {
  Write-Host "Opening the host console on this laptop (one-time link)..." -ForegroundColor Green
  Start-Process $link
}
Write-Host "Phone/desktop app: http://127.0.0.1:8740/ $(if ($Lan) {'(Wi-Fi phone: see the LAN address in the host console)'})$(if ($Usb) {'(USB phone: same address, or scan the pairing QR code)'})"
Write-Host "Logs:              $logs"
Write-Host "Stop everything:   powershell -ExecutionPolicy Bypass -File scripts\stop.ps1"
