@echo off
setlocal EnableDelayedExpansion
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set OLLAMA_KEEP_ALIVE=0

REM Use DETERMINEX_PYTHON env var if set, otherwise find python on PATH
if "%DETERMINEX_PYTHON%"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do set PYTHON=%%i
) else (
    set PYTHON=%DETERMINEX_PYTHON%
)

echo ==============================================
echo [DETERMINEX] BOOTING SYSTEM
echo ==============================================

REM Pin the project root so Rust's project_root() finds scripts/ even when
REM CARGO_TARGET_DIR redirects the exe to a different drive (T:\determinex-target).
for %%I in ("%~dp0..\..") do set DETERMINEX_ROOT=%%~fI

REM Step 1: Dependency audit
echo [BOOT] Running dependency audit...
cd /d "%DETERMINEX_ROOT%"
%PYTHON% "%DETERMINEX_ROOT%\tools\dependency_auditor.py"
echo.

REM Step 1b: Session disk health hint (non-blocking, informational only)
for /f %%i in ('dir /b /ad "%DETERMINEX_ROOT%\sessions" 2^>nul ^| find /c /v ""') do set SESSION_COUNT=%%i
if defined SESSION_COUNT (
    if !SESSION_COUNT! GTR 50 (
        echo [BOOT] INFO: %SESSION_COUNT% session directories in sessions/. Consider running:
        echo [BOOT]       python scripts\cleanup_sessions.py --older-than 30 --dry-run
        echo.
    )
)

REM Step 1c: Seed knowledge base into vector DB (idempotent — skips if already done)
echo [BOOT] Seeding knowledge base (one-time, skips if already seeded)...
%PYTHON% "%DETERMINEX_ROOT%\scripts\seed_knowledge_base.py"
echo.

REM Step 2: Kill stale Determinex Tauri dev windows (only the cmd window boot.bat opens)
echo [BOOT] Cleaning up stale processes...
taskkill /F /FI "WINDOWTITLE eq Determinex Tauri*" 2>nul
echo.

REM Step 3: Hive backend — now runs as a bundled sidecar (no Docker required)
echo [BOOT] Hive backend: sidecar mode active (Docker not required).
echo [BOOT] The determinex-hive binary is spawned on-demand by the Tauri backend.
echo.

REM Step 4: Verify Ollama is reachable
echo [BOOT] Checking Ollama daemon...
curl -s -o nul -w "%%{http_code}" http://localhost:11434/api/tags 2>nul | findstr "200" >nul
if %ERRORLEVEL% EQU 0 (
    echo [BOOT] Ollama is running on port 11434.
) else (
    echo [BOOT] WARNING: Ollama not detected on port 11434.
    echo [BOOT] Start Ollama and pull a model: ollama pull qwen2.5-coder:7b
)
echo.

REM Step 5: Clear port 3000 and any stale Next.js dev processes
echo [BOOT] Ensuring port 3000 is free for Tauri dev server...
REM Kill by port (TCP listener) — reliable even when netstat parse fails
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Write-Host '[BOOT] Killing PID' $_.OwningProcess 'on port 3000'; Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" 2>nul
REM Kill any node.exe with 'next' in its command line (catches servers still binding to port)
wmic process where "Name='node.exe' and CommandLine like '%%next%%'" call terminate >nul 2>&1
echo.

REM Step 6: Launch the Tauri development build
echo [BOOT] Launching Determinex via cargo tauri dev...
cd /d "%DETERMINEX_ROOT%\frontend"
start "Determinex" /D "%DETERMINEX_ROOT%\frontend" cmd /c "npx tauri dev & pause"

echo.
echo ==============================================
echo [DETERMINEX] Tauri dev build launching.
echo   The Rust backend compiles first, then
echo   Next.js starts on :3000 and the native
echo   window opens automatically.
echo ==============================================
timeout /t 3 >nul
endlocal
