# One-time setup on Windows. From the repo root:  .\scripts\setup.ps1
# Works online (installs from PyPI/npm) or offline (uses vendor\wheels and a prebuilt frontend\dist
# from a release zip made by scripts\build-release.ps1).
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$py = $null
foreach ($candidate in @("py -3", "python")) {
    try {
        & cmd /c "$candidate --version" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $py = $candidate; break }
    } catch {}
}
if (-not $py) { throw "Python 3.10 or newer was not found. Install it from python.org and run this script again." }

Write-Host "Creating virtual environment in .venv"
& cmd /c "$py -m venv .venv"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

if (Test-Path "vendor\wheels") {
    Write-Host "Installing Python packages from vendor\wheels (offline)"
    & $venvPy -m pip install --no-index --find-links vendor\wheels -r backend\requirements.txt
} else {
    Write-Host "Installing Python packages from PyPI"
    & $venvPy -m pip install -r backend\requirements.txt
}
if ($LASTEXITCODE -ne 0) {
    throw "Installing Python packages failed. If your network blocks PyPI, use a release zip that includes vendor\wheels."
}

if (Test-Path "frontend\dist\index.html") {
    Write-Host "Frontend is already built (frontend\dist)"
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "Building the frontend"
    Push-Location frontend
    npm install --no-audit --no-fund
    npm run build
    Pop-Location
} else {
    throw "No prebuilt frontend and npm was not found. Install Node.js 20+ or use a release zip."
}

Write-Host ""
Write-Host "Done. Start the tool with:  .\scripts\run.ps1"
