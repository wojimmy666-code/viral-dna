@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-server.ps1" -Config "%~dp0..\config\deploy.json"
if errorlevel 1 goto failed
echo Completed.
pause
exit /b 0
:failed
echo FAILED. Read the error above before continuing.
pause
exit /b 1
