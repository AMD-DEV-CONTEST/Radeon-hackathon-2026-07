@echo off
chcp 65001 >nul
title Motus Agent

echo ============================================
echo   Motus Agent - starting...
echo ============================================
echo.

cd /d "%~dp0"

rem Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

rem Setup dependencies - Priority: .deps > venv
if exist ".deps" (
    echo [INFO] Using bundled deps
    set "PYTHONPATH=%cd%\.deps;%cd%\.libs;%PYTHONPATH%"
    echo [INFO] PYTHONPATH=%cd%\.deps;%cd%\.libs
) else (
    if exist "venv" (
        echo [INFO] Activating virtual env
        call venv\Scripts\activate
    ) else (
        echo [INFO] First time setup - installing dependencies...
        python -m venv venv
        call venv\Scripts\activate
        pip install -r requirements.txt
        echo [DONE] Dependencies installed
        echo.
    )
)

rem Check .env
if not exist ".env" (
    echo [WARN] .env file not found. Please configure API key and endpoint.
    echo.
)

echo [INFO] Starting service...
echo [INFO] URL: http://localhost:8000
echo [INFO] Press Ctrl+C to stop
echo.

python main.py

pause
