@echo off
setlocal

for %%I in ("%~dp0..") do set "CROWLEY_ROOT=%%~fI"
set "CROWLEY_PYTHON=%CROWLEY_ROOT%\venv\Scripts\python.exe"
set "CROWLEY_CLOUDFLARED=%LOCALAPPDATA%\Cloudflared\cloudflared.exe"
set "CROWLEY_CONFIG=%CROWLEY_ROOT%\cloudflared\config.yml"
set "CROWLEY_LOG_DIR=%CROWLEY_ROOT%\.crowley\chatgpt_bridge"
set "CROWLEY_LOG=%CROWLEY_LOG_DIR%\service.log"

if not exist "%CROWLEY_LOG_DIR%" mkdir "%CROWLEY_LOG_DIR%"

:restart
"%CROWLEY_PYTHON%" "%CROWLEY_ROOT%\scripts\ensure_crowley_bus.py"
if errorlevel 1 (
  echo [%DATE% %TIME%] Crowley bus startup failed. Retrying in 10 seconds.>>"%CROWLEY_LOG%"
  timeout /t 10 /nobreak >nul
  goto restart
)

tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | find /I "cloudflared.exe" >nul
if not errorlevel 1 (
  timeout /t 10 /nobreak >nul
  goto restart
)

"%CROWLEY_CLOUDFLARED%" tunnel --config "%CROWLEY_CONFIG%" run >>"%CROWLEY_LOG%" 2>&1
echo [%DATE% %TIME%] cloudflared exited. Restarting in 10 seconds.>>"%CROWLEY_LOG%"
timeout /t 10 /nobreak >nul
goto restart
