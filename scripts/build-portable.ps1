# Build a self-contained Windows package: unzip anywhere, double-click "Log Evaluation Tool.bat".
# It carries its own private Python and every dependency, so the other PC needs no installs
# (no Python, no Node, no admin rights, no internet).
#
#   .\scripts\build-portable.ps1
#
# Run it on a Windows PC with internet access, from a working checkout (needs .venv and npm).
# Output: release\LogEvaluationTool-win64.zip
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "Run scripts\setup.ps1 first (this script reuses its Python to install packages)." }
$ver = (& $venvPy -c "import sys; print('%d.%d.%d' % sys.version_info[:3])").Trim()
$short = ($ver -split '\.')[0..1] -join ''          # 3.12.7 -> 312

# 1. Build the interface
Push-Location frontend
npm install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
Pop-Location

# 2. Private Python (the official "embeddable" build, same version as .venv)
$cache = Join-Path $root "release\cache"
New-Item -ItemType Directory -Force $cache | Out-Null
$embed = Join-Path $cache "python-$ver-embed-amd64.zip"
if (-not (Test-Path $embed)) {
    Write-Host "Downloading Python $ver (embeddable)"
    Invoke-WebRequest "https://www.python.org/ftp/python/$ver/python-$ver-embed-amd64.zip" -OutFile $embed
}
$stage = Join-Path $root "release\stage"
$app = Join-Path $stage "LogEvaluationTool"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $app | Out-Null
Expand-Archive $embed -DestinationPath (Join-Path $app "python")

# 3. Let that Python see its packages, the app folder, and pywin32
$sp = Join-Path $app "python\Lib\site-packages"
New-Item -ItemType Directory -Force $sp | Out-Null
@"
python$short.zip
.
Lib\site-packages
Lib\site-packages\win32
Lib\site-packages\win32\lib
..
import site
"@ | Set-Content (Join-Path $app "python\python$short._pth") -Encoding ascii

# 4. Dependencies
& $venvPy -m pip install --no-warn-script-location --target $sp -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installing packages failed" }
# pywin32 needs its two runtime DLLs next to python.exe when it is not installed the normal way
Copy-Item (Join-Path $sp "pywin32_system32\*.dll") (Join-Path $app "python") -ErrorAction SilentlyContinue
Get-ChildItem $sp -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem $sp -Recurse -Directory -Filter "tests" | Where-Object { $_.FullName -notmatch "pywin32" } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 5. The app itself
Copy-Item backend, tools -Destination $app -Recurse
Get-ChildItem (Join-Path $app "backend") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item (Join-Path $app "backend\tests") -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $app "frontend") | Out-Null
Copy-Item frontend\dist -Destination (Join-Path $app "frontend") -Recurse
Copy-Item "Log Evaluation Tool.bat", "Log Evaluation Tool (phone).bat", README.md -Destination $app
@"
Log Evaluation Tool
===================
1. Unzip this folder anywhere (not inside the zip).
2. Double-click  "Log Evaluation Tool.bat".  Your browser opens the tool.
3. Close the small minimised "Log Evaluation Tool" window to stop it.

To use it on a phone on the same Wi-Fi, double-click  "Log Evaluation Tool (phone).bat"  instead and
scan the QR code it shows. Windows asks once whether Python may use the network: choose Private.

Nothing needs installing. Your logs and library are kept in
%LOCALAPPDATA%\Log Evaluation Tool  so a new version never loses them.

Converting .LRD logs needs LifeView installed on this PC. Everything else works without it.
"@ | Set-Content (Join-Path $app "START HERE.txt") -Encoding ascii

# 6. Zip it
$zip = Join-Path $root "release\LogEvaluationTool-win64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
$mb = [math]::Round((Get-Item $zip).Length / 1MB)
Write-Host "Wrote $zip ($mb MB)"
