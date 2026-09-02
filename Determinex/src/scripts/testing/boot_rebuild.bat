@echo off
REM boot_rebuild.bat — Force-rebuild the Hive Docker image, then boot normally.
REM
REM Use this when you've updated the Dockerfile or docker-compose.hive.yml.
REM Normal boot.bat does NOT rebuild the image (by design — it's slow).
REM This script explicitly passes --build to trigger a full image rebuild.
REM
REM Expected rebuild time: 10-20 min (Rust toolchain inside Docker).
REM Subsequent boots via boot.bat will be instant.

setlocal EnableDelayedExpansion
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ==============================================
echo [DETERMINEX] FORCED REBUILD BOOT
echo ==============================================
echo [REBUILD] This will rebuild the Hive Docker image.
echo [REBUILD] Expected time: 10-20 minutes on first run.
echo.
pause

REM Rebuild the image
echo [REBUILD] Building Hive container (this takes a while)...
docker compose -f "%~dp0docker\docker-compose.hive.yml" up -d --build
if %ERRORLEVEL% EQU 0 (
    echo [REBUILD] Hive container rebuilt and started.
) else (
    echo [REBUILD] ERROR: Container rebuild failed. Check Docker logs.
    pause
    exit /b 1
)

echo.
echo [REBUILD] Image rebuilt. Launching Determinex...
echo.

REM Launch Tauri
cd /d "%~dp0frontend"
start "Determinex Tauri" cmd /k "npx tauri dev"

echo ==============================================
echo [DETERMINEX] Tauri dev build launching.
echo ==============================================
timeout /t 3 >nul
endlocal
