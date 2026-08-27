@echo off
setlocal EnableExtensions
chcp 65001 >nul
title ViralDNA Launcher

set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "LOCAL_ENV_FILE=%PROJECT_ROOT%\.env.local"
if exist "%LOCAL_ENV_FILE%" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%LOCAL_ENV_FILE%") do (
    if /I "%%A"=="VIRAL_DNA_YTDLP_COOKIE_FILE" set "VIRAL_DNA_YTDLP_COOKIE_FILE=%%B"
    if /I "%%A"=="VIRAL_DNA_ASR_PROVIDER" set "VIRAL_DNA_ASR_PROVIDER=%%B"
    if /I "%%A"=="VIRAL_DNA_ASR_MODEL" set "VIRAL_DNA_ASR_MODEL=%%B"
    if /I "%%A"=="VIRAL_DNA_ASR_DEVICE" set "VIRAL_DNA_ASR_DEVICE=%%B"
    if /I "%%A"=="VIRAL_DNA_ASR_COMPUTE_TYPE" set "VIRAL_DNA_ASR_COMPUTE_TYPE=%%B"
    if /I "%%A"=="VIRAL_DNA_ASR_LANGUAGE" set "VIRAL_DNA_ASR_LANGUAGE=%%B"
    if /I "%%A"=="VIRAL_DNA_ASR_MODEL_DIR" set "VIRAL_DNA_ASR_MODEL_DIR=%%B"
    if /I "%%A"=="VIRAL_DNA_OCR_PROVIDER" set "VIRAL_DNA_OCR_PROVIDER=%%B"
    if /I "%%A"=="VIRAL_DNA_OCR_MODEL" set "VIRAL_DNA_OCR_MODEL=%%B"
    if /I "%%A"=="VIRAL_DNA_OCR_MIN_CONFIDENCE" set "VIRAL_DNA_OCR_MIN_CONFIDENCE=%%B"
    if /I "%%A"=="VIRAL_DNA_VLM_PROVIDER" set "VIRAL_DNA_VLM_PROVIDER=%%B"
    if /I "%%A"=="VIRAL_DNA_VLM_MODEL_ALIAS" set "VIRAL_DNA_VLM_MODEL_ALIAS=%%B"
    if /I "%%A"=="VIRAL_DNA_MODEL_LAST_VALIDATED_AT" set "VIRAL_DNA_MODEL_LAST_VALIDATED_AT=%%B"
    if /I "%%A"=="VIRAL_DNA_MODEL_PROFILE" set "VIRAL_DNA_MODEL_PROFILE=%%B"
    if /I "%%A"=="VIRAL_DNA_MODEL_CATALOG" set "VIRAL_DNA_MODEL_CATALOG=%%B"
    if /I "%%A"=="VIRAL_DNA_MODEL_PRICING" set "VIRAL_DNA_MODEL_PRICING=%%B"
    if /I "%%A"=="VIRAL_DNA_MODEL_MAX_ATTEMPTS" set "VIRAL_DNA_MODEL_MAX_ATTEMPTS=%%B"
    if /I "%%A"=="VIRAL_DNA_MODEL_TIMEOUT_SECONDS" set "VIRAL_DNA_MODEL_TIMEOUT_SECONDS=%%B"
    if /I "%%A"=="DASHSCOPE_API_KEY" set "DASHSCOPE_API_KEY=%%B"
    if /I "%%A"=="DASHSCOPE_BASE_URL" set "DASHSCOPE_BASE_URL=%%B"
  )
)
set "WEB_URL=http://127.0.0.1:4174"
set "API_URL=http://127.0.0.1:8000/health"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "API_STATE_HELPER=%PROJECT_ROOT%\scripts\api-service-state.ps1"
set "WEB_RUNNING=0"
set "API_RUNNING=0"

if defined PROJECT_LAUNCHER_MANAGED goto :managed_start

echo.
echo [ViralDNA] Project root: %PROJECT_ROOT%
if defined VIRAL_DNA_YTDLP_COOKIE_FILE (
  if exist "%VIRAL_DNA_YTDLP_COOKIE_FILE%" (
    echo [ViralDNA] Link collector Cookie file is configured.
  ) else (
    echo [ViralDNA] WARNING: Configured Cookie file does not exist.
  )
)
echo [ViralDNA] Checking services...

call :is_web_ready
if not errorlevel 1 set "WEB_RUNNING=1"

call :api_state
set "API_STATE=%errorlevel%"
if "%API_STATE%"=="0" set "API_RUNNING=1"
if "%API_STATE%"=="2" (
  echo [ViralDNA] API source or workspace schema changed. Restarting the stale API...
  call :stop_stale_api
  if errorlevel 1 goto :failed
)
if "%API_STATE%"=="3" (
  echo [ViralDNA] ERROR: Port 8000 is occupied by another service.
  goto :failed
)
if "%API_STATE%"=="4" (
  echo [ViralDNA] ERROR: API compatibility check failed.
  goto :failed
)

if "%API_RUNNING%"=="1" (
  echo [ViralDNA] API is already running on port 8000.
) else (
  call :prepare_api
  if errorlevel 1 goto :failed
)

if "%WEB_RUNNING%"=="1" (
  echo [ViralDNA] Web is already running on port 4174.
) else (
  call :prepare_web
  if errorlevel 1 goto :failed
)

if "%API_RUNNING%"=="1" if "%WEB_RUNNING%"=="1" goto :ready

if "%API_RUNNING%"=="0" (
  echo [ViralDNA] Starting API...
  start "ViralDNA API" /D "%PROJECT_ROOT%" "%ComSpec%" /k ""%PYTHON_EXE%" -m uvicorn viral_dna_api.main:app --app-dir services/api/src --host 127.0.0.1 --port 8000"
)

if "%WEB_RUNNING%"=="0" (
  echo [ViralDNA] Starting Web...
  start "ViralDNA Web" /D "%PROJECT_ROOT%\apps\web" "%ComSpec%" /k "npm run dev -- --host 127.0.0.1 --port 4174 --strictPort"
)

echo [ViralDNA] Waiting for both services...
set /a WAIT_COUNT=0

:wait_for_services
call :is_api_ready
if errorlevel 1 goto :not_ready
call :is_web_ready
if errorlevel 1 goto :not_ready
goto :ready

:not_ready
set /a WAIT_COUNT+=1
if %WAIT_COUNT% GEQ 30 goto :startup_timeout
timeout /t 1 /nobreak >nul
goto :wait_for_services

:ready
echo [ViralDNA] Ready: %WEB_URL%
if /I not "%~1"=="--no-browser" start "" "%WEB_URL%"
exit /b 0

:managed_start
echo.
echo [ViralDNA] Starting in project-launcher managed mode...
call :prepare_api
if errorlevel 1 goto :failed
call :prepare_web
if errorlevel 1 goto :failed
node "%PROJECT_ROOT%\scripts\managed-launcher.mjs"
set "MANAGED_EXIT=%errorlevel%"
exit /b %MANAGED_EXIT%

:prepare_api
if not exist "%PYTHON_EXE%" (
  where python >nul 2>&1
  if errorlevel 1 (
    echo [ViralDNA] ERROR: Python 3.11 or newer was not found.
    exit /b 1
  )
  echo [ViralDNA] Creating Python virtual environment...
  python -m venv "%PROJECT_ROOT%\.venv"
  if errorlevel 1 exit /b 1
)

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
  echo [ViralDNA] ERROR: The Python virtual environment is not usable.
  echo [ViralDNA] Remove .venv, install Python 3.11+, and run this file again.
  exit /b 1
)

"%PYTHON_EXE%" -c "import httpx, numpy, onnxruntime, opencc, uvicorn, viral_dna_api, yt_dlp" >nul 2>&1
if errorlevel 1 (
  echo [ViralDNA] Installing API dependencies...
  "%PYTHON_EXE%" -m pip install -e "%PROJECT_ROOT%\services\api[dev]"
  if errorlevel 1 exit /b 1
)

set "LOCAL_AI_REQUIRED=0"
if /I "%VIRAL_DNA_ASR_PROVIDER%"=="faster-whisper" set "LOCAL_AI_REQUIRED=1"
if /I "%VIRAL_DNA_ASR_PROVIDER%"=="faster_whisper" set "LOCAL_AI_REQUIRED=1"
if /I "%VIRAL_DNA_ASR_PROVIDER%"=="whisper" set "LOCAL_AI_REQUIRED=1"
if /I "%VIRAL_DNA_OCR_PROVIDER%"=="rapidocr" set "LOCAL_AI_REQUIRED=1"
if /I "%VIRAL_DNA_OCR_PROVIDER%"=="rapid-ocr" set "LOCAL_AI_REQUIRED=1"
if /I "%VIRAL_DNA_OCR_PROVIDER%"=="rapid_ocr" set "LOCAL_AI_REQUIRED=1"
if "%LOCAL_AI_REQUIRED%"=="1" (
  "%PYTHON_EXE%" -c "import faster_whisper, onnxruntime, rapidocr" >nul 2>&1
  if errorlevel 1 (
    echo [ViralDNA] Installing optional local ASR/OCR dependencies...
    "%PYTHON_EXE%" -m pip install -e "%PROJECT_ROOT%\services\api[local-ai]"
    if errorlevel 1 exit /b 1
  )
)
exit /b 0

:prepare_web
where node >nul 2>&1
if errorlevel 1 (
  echo [ViralDNA] ERROR: Node.js 20.19 or newer was not found.
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ViralDNA] ERROR: npm was not found.
  exit /b 1
)

if not exist "%PROJECT_ROOT%\node_modules\.bin\vite.cmd" (
  echo [ViralDNA] Installing Web dependencies...
  pushd "%PROJECT_ROOT%"
  call npm install
  if errorlevel 1 (
    popd
    exit /b 1
  )
  popd
)
exit /b 0

:is_api_ready
call :api_state >nul 2>&1
exit /b %errorlevel%

:api_state
powershell -NoProfile -ExecutionPolicy Bypass -File "%API_STATE_HELPER%" -Mode check -HealthUrl "%API_URL%" -Port 8000
exit /b %errorlevel%

:stop_stale_api
powershell -NoProfile -ExecutionPolicy Bypass -File "%API_STATE_HELPER%" -Mode stop-stale -HealthUrl "%API_URL%" -Port 8000
exit /b %errorlevel%

:is_web_ready
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $result = Invoke-WebRequest -UseBasicParsing -Uri '%WEB_URL%' -TimeoutSec 2; if ($result.StatusCode -eq 200 -and $result.Content -match 'ViralDNA') { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:startup_timeout
echo.
echo [ViralDNA] ERROR: Services did not become ready within 30 seconds.
if defined PROJECT_LAUNCHER_MANAGED (
  echo [ViralDNA] Check this launch run's API and Web logs for details.
) else (
  echo [ViralDNA] Check the API and Web windows for details.
)
if not defined PROJECT_LAUNCHER_MANAGED pause
exit /b 1

:failed
echo.
echo [ViralDNA] ERROR: Startup preparation failed.
if not defined PROJECT_LAUNCHER_MANAGED pause
exit /b 1
