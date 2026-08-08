@echo off
setlocal enabledelayedexpansion

echo ========================================
echo Screen-AI: Stop Local Servers
echo ========================================
echo.

set PORTS=8000 8443
set STOPPED=0

for %%P in (%PORTS%) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr /r /c:":%%P .*LISTENING"') do (
        echo Stopping process %%A on port %%P...
        taskkill /F /PID %%A >nul 2>&1
        if errorlevel 1 (
            echo Could not stop PID %%A. It may already be closed.
        ) else (
            set STOPPED=1
        )
    )
)

if "%STOPPED%"=="0" (
    echo No Screen-AI server was listening on ports 8000 or 8443.
) else (
    echo Screen-AI server ports are closed.
)

echo.
pause
