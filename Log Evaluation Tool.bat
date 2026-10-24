@echo off
setlocal
cd /d "%~dp0"
set PORT=8000
set URL=http://127.0.0.1:%PORT%

if not exist ".venv\Scripts\python.exe" (
  echo The tool is not set up on this computer yet.
  echo Open PowerShell in this folder and run:  .\scripts\setup.ps1
  pause
  exit /b 1
)

rem Already running? Then just open it.
curl -s -o nul -f %URL%/api/health && goto open

echo Starting Log Evaluation Tool...
start "Log Evaluation Tool - close this window to stop it" /min ".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port %PORT%

set /a tries=0
:wait
set /a tries+=1
if %tries% gtr 40 goto failed
curl -s -o nul -f %URL%/api/health && goto open
ping -n 2 127.0.0.1 >nul
goto wait

:failed
echo The tool did not start. Open the minimised "Log Evaluation Tool" window to see why.
pause
exit /b 1

:open
start "" %URL%
exit /b 0
