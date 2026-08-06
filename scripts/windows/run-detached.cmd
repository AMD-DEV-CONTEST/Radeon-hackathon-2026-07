@echo off
setlocal
set ROOT=C:\Users\AMD\dev\botversex
set API_PY=%ROOT%\apps\api\.venv\Scripts\python.exe
set RT_PY=%ROOT%\apps\realtime\.venv\Scripts\python.exe
set NPM=C:\Program Files\nodejs\npm.cmd
set LOGDIR=%TEMP%

set BOTVERSEX_ROBOTS_CONFIG=%ROOT%\apps\realtime\config\robots.windows-demo.json
set REACHY_MINI_SDK_PATH=C:\Users\AMD\sdk\reachy_mini_Allan
set BOTVERSEX_SEEED_CONVERSATION_DIR=%USERPROFILE%\.local\share\botversex\seeed_reachymini_conversation
set BOTVERSEX_SEEED_KEYS_FILE=%USERPROFILE%\.config\botversex\reachy_seeed_keys.json

call "%~dp0stop-detached.cmd" >nul 2>&1

start "botversex-api" /MIN /D "%ROOT%\apps\api" "%API_PY%" -m uvicorn app.main:app --port 8000 --app-dir .
start "botversex-realtime" /MIN /D "%ROOT%" "%RT_PY%" "%ROOT%\apps\realtime\run_api.py" --http
start "botversex-web" /MIN /D "%ROOT%\apps\web" "%NPM%" run dev -- --host 0.0.0.0
start "botversex-watchdog" /MIN /D "%ROOT%" "%~dp0watchdog-realtime.cmd"

echo BotverseX detached: API 8000, Realtime 8002, Web 5173, Watchdog
