# Start the tool and open it in the default browser.
# Binds to 127.0.0.1 only, so it is not visible on the network. With -Phone it also opens the tool to
# phones on the same Wi-Fi (a QR code appears in the tool); they need the link's key to get in.
param([switch]$Phone)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "Run scripts\setup.ps1 first." }
$port = 8000
$bind = "127.0.0.1"
$open = "http://127.0.0.1:$port"
if ($Phone) {
  $env:LET_LAN = "1"
  $bind = "0.0.0.0"
  $open = "$open/#phone"
  Write-Host "Phone access is on. If Windows asks about Python and the network, choose Private networks."
}
Start-Process $open
& $venvPy -m uvicorn backend.app.main:app --host $bind --port $port --no-proxy-headers
