# Run on a machine WITH internet access to make a zip that installs on a locked-down laptop.
# The zip contains the built frontend and Python wheels for Windows, so setup.ps1 needs no network.
#   .\scripts\build-release.ps1 -PythonVersion 3.12
# Set -PythonVersion to the Python version installed on the TARGET laptop (for example 3.11, 3.12, 3.13).
param([string]$PythonVersion = "3.12")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Push-Location frontend
npm install --no-audit --no-fund
npm run build
Pop-Location

Remove-Item -Recurse -Force vendor -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force vendor\wheels | Out-Null
python -m pip download -r backend\requirements.txt -d vendor\wheels `
    --platform win_amd64 --python-version $PythonVersion --only-binary=:all:
if ($LASTEXITCODE -ne 0) { throw "Could not download wheels for Python $PythonVersion on Windows." }

New-Item -ItemType Directory -Force release | Out-Null
$zip = "release\log-evaluation-tool-win-py$PythonVersion.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Force -DestinationPath $zip -Path backend, tools, scripts, samples, design, frontend\dist, vendor, README.md, PRODUCT.md
Write-Host "Wrote $zip"
