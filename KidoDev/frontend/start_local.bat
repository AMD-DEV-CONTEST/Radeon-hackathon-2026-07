@echo off
echo.
echo ========================================
echo   Kido Dev -- Frontend (Local Mode)
echo   Backend: http://localhost:8000
echo ========================================
echo.
echo [1] Checking Node.js...
node --version
if errorlevel 1 (
    echo ERROR: Node.js not found. Install Node.js 18+
    pause
    exit /b 1
)
echo.
echo [2] Installing dependencies...
call npm install
echo.
echo [3] Setting env to local mode...
echo    VITE_AGENT_BACKEND_URL = http://localhost:8000
echo    VITE_BACKEND_WS_URL    = ws://localhost:8000
echo.
echo [4] Starting Vite dev server...
echo     Frontend: http://localhost:5173
echo     Backend:  http://localhost:8000 (start separately)
echo     Press Ctrl+C to stop
echo.
call npm run dev
pause
