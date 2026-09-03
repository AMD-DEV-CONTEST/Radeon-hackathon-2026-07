@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if errorlevel 1 (
        echo Python 3.10 or newer is required.
        pause
        exit /b 1
    )
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :failed

start "AutoFlow" ".venv\Scripts\autoflow-gui.exe"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"
exit /b 0

:failed
echo AutoFlow setup failed. Check the message above.
pause
exit /b 1
