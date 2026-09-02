@echo off
REM AetherDB v1.31.2 - portable Windows startup
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo Run: python -m venv venv
    echo Then: pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] Using: venv\Scripts\python.exe
echo [OK] Initializing local runtime files...
venv\Scripts\python.exe scripts\init_runtime.py
if errorlevel 1 (
    echo [ERROR] Runtime initialization failed.
    pause
    exit /b 1
)
echo [OK] Starting Worldview Database...
venv\Scripts\python.exe main.py
pause
