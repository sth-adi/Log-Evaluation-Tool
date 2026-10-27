@echo off
rem Starts the tool and opens it to phones on the same Wi-Fi. A QR code appears in the tool.
call "%~dp0Log Evaluation Tool.bat" phone
exit /b %errorlevel%
