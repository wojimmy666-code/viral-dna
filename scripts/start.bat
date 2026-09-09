@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Keep this public entry stable; forward every argument and the exit code.
call "%~dp0dev\start-dev.bat" %*
exit /b %errorlevel%
