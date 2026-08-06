@echo off
REM Keep realtime (:8002) alive — Vite 502 when this dies.
setlocal
set ROOT=C:\Users\AMD\dev\botversex
set RT_PY=%ROOT%\apps\realtime\.venv\Scripts\python.exe
set LOGDIR=%TEMP%
set BOTVERSEX_ROBOTS_CONFIG=%ROOT%\apps\realtime\config\robots.windows-demo.json
set REACHY_MINI_SDK_PATH=C:\Users\AMD\sdk\reachy_mini_Allan
set BOTVERSEX_SEEED_CONVERSATION_DIR=%USERPROFILE%\.local\share\botversex\seeed_reachymini_conversation
set BOTVERSEX_SEEED_KEYS_FILE=%USERPROFILE%\.config\botversex\reachy_seeed_keys.json

:loop
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri http://127.0.0.1:8002/api/setup/health -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==0 (
  timeout /t 15 /nobreak >nul
  goto loop
)

echo [%DATE% %TIME%] realtime down — restarting >> "%LOGDIR%\botversex_watchdog.log"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8002" ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>&1
timeout /t 2 /nobreak >nul
start "botversex-realtime" /MIN /D "%ROOT%" "%RT_PY%" "%ROOT%\apps\realtime\run_api.py" --http
timeout /t 20 /nobreak >nul
goto loop
