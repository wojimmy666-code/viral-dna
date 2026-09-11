@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-manual-iis-update.ps1"
if errorlevel 1 goto failed
echo Update completed. No service was started and no IIS setting was changed.
pause
exit /b 0
:failed
echo FAILED. Read the error above before continuing.
pause
exit /b 1
