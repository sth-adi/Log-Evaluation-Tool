@echo off
rem Starts the tool and opens it to teammates, who sign in with an account. Make accounts under More, Team.
call "%~dp0Log Evaluation Tool.bat" team
exit /b %errorlevel%
