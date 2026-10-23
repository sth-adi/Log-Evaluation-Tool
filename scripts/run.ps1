# Start the tool and open it in the default browser.
# Binds to 127.0.0.1 only, so it is not visible on the network.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "Run scripts\setup.ps1 first." }
$port = 8000
Start-Process "http://127.0.0.1:$port"
& $venvPy -m uvicorn backend.app.main:app --host 127.0.0.1 --port $port
