@echo off
setlocal
chcp 65001 >nul
set "supplementServer=C:\Projects\ViralDNA"
if not "%~1"=="" set "supplementServer=%~1"
set "supplementPython=%supplementServer%\.server\tools\python\python.exe"
if not exist "%supplementPython%" (
  echo Server Python not found: "%supplementPython%"
  pause
  exit /b 1
)
"%supplementPython%" -B -I -X utf8 "%~dp0scripts\maintenance\supplement-menu.py" --package "%~dp0." --server-root "%supplementServer%"
set "supplementExit=%errorlevel%"
pause
exit /b %supplementExit%
