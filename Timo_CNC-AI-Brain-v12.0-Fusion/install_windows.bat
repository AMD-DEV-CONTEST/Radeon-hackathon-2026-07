@echo off
chcp 65001 >nul
title Union·由你 CNC AI Brain v11.0.8 — One-Click Install
cd /d %~dp0

echo.
echo ============================================================
echo   Union·由你 — CNC AI 工艺大脑 v11.0.8
echo   One-Click Install (Windows)
echo   Cloud: DeepSeek/SiliconFlow/Grok/OpenAI/Anthropic
echo   Local: Ollama auto-detect
echo ============================================================
echo.

:: ── Step 1: Python ──
echo [1/4] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] Python 3.10+ not found
    echo   Download: https://www.python.org/downloads/
    echo   IMPORTANT: Check "Add Python to PATH" during install!
    echo.
    echo   After installing Python, run this script again.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo   Python %PYVER% [OK]

:: ── Step 2: pip install ──
echo.
echo [2/4] Installing dependencies...
echo   (Using Tsinghua mirror for faster download in China)
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet 2>nul
if %errorlevel% neq 0 (
    echo   [WARN] Tsinghua mirror failed, trying default PyPI...
    pip install -r requirements.txt --quiet 2>nul
    if %errorlevel% neq 0 (
        echo   [ERROR] pip install failed!
        echo   Try manually: pip install -r requirements.txt
        pause
        exit /b 1
    )
)
echo   Dependencies [OK]

:: ── Step 3: Ollama (optional) ──
echo.
echo [3/4] Checking Ollama (optional, for local AI)...
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo   Ollama not installed — cloud models will be used.
    echo   To install local models: https://ollama.com/download
) else (
    echo   Ollama found [OK]
    ollama list 2>nul | findstr "qwen" >nul
    if %errorlevel% neq 0 (
        echo   Pulling qwen2.5:1.5b (~1GB)...
        ollama pull qwen2.5:1.5b 2>nul
    ) else (
        echo   Local model ready [OK]
    )
)

:: ── Step 4: Launch ──
echo.
echo [4/4] Starting service...
echo.
echo ============================================================
echo   READY!
echo   Open: http://localhost:7862
echo   Models: http://localhost:7862/api/models
echo   Press Ctrl+C to stop
echo ============================================================
echo.

:: Find available port
set PORT=7862
:check_port
netstat -ano | findstr ":%PORT% " >nul 2>&1
if %errorlevel% equ 0 (
    set /a PORT=PORT+1
    if %PORT% gtr 7870 (
        echo   [ERROR] Ports 7862-7870 all occupied
        pause
        exit /b 1
    )
    goto check_port
)

python -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
pause
