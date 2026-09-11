@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-server.ps1" -Config "%~dp0..\config\deploy.json" -Action verify-public
if errorlevel 1 goto failed
echo HTTPS entry verified. No service or IIS setting was changed.
pause
exit /b 0
:failed
echo HTTPS check failed. Keep current files and read the error above.
pause
exit /b 1
