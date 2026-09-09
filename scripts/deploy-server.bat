@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title ViralDNA Server Deployment
rem Parse the whole block before Git can update this entry on disk.
(
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\deploy-server.ps1" %*
  if errorlevel 1 (
    echo [ViralDNA] Deployment failed. See the message and log path above.
    pause
    exit /b 1
  )
  exit /b 0
)
