@echo off
setlocal
cd /d "%~dp0"
set PORT=8000
set URL=http://127.0.0.1:%PORT%

rem "Log Evaluation Tool.bat phone" (or the "(phone)" launcher) also opens the tool to phones on the same Wi-Fi.
rem Without it the tool only answers this PC.
set HOST=127.0.0.1
set OPEN=%URL%
if /i "%~1"=="phone" (
  set HOST=0.0.0.0
  set LET_LAN=1
  set OPEN=%URL%/#phone
)

rem Packaged copy: use the Python that ships beside this file, and keep logs outside the folder
rem so unpacking a newer version never loses them.
set PY=.venv\Scripts\python.exe
if exist "python\python.exe" set PY=python\python.exe
if exist "python\python.exe" if not defined LET_DATA_DIR set "LET_DATA_DIR=%LOCALAPPDATA%\Log Evaluation Tool"

if not exist "%PY%" (
  echo The tool is not set up on this computer yet.
  echo Open PowerShell in this folder and run:  .\scripts\setup.ps1
  pause
  exit /b 1
)

rem Already running? Then just open it, unless phone access was asked for and it is not on.
curl -s -o nul -f %URL%/api/health && goto running

if /i "%~1"=="phone" (
  echo Phone access is on. When Windows asks whether to let Python use the network,
  echo choose "Private networks" and press Allow. Then scan the code shown in the tool.
  echo.
)
echo Starting Log Evaluation Tool...
start "Log Evaluation Tool - close this window to stop it" /min "%PY%" -m uvicorn backend.app.main:app --host %HOST% --port %PORT% --no-proxy-headers

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

:running
if /i not "%~1"=="phone" goto open
curl -s %URL%/api/sharing | find "sharing-on" >nul && goto open
echo The tool is already running without phone access.
echo Close its minimised "Log Evaluation Tool" window in the taskbar, then open this launcher again.
pause
exit /b 1

:open
start "" "%OPEN%"
exit /b 0
