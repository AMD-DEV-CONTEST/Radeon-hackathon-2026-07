@echo off
:: THEMIS Quick Start — Team Alchemy
:: Run from the themis\ directory

echo.
echo  ======================================
echo   THEMIS — AMD AI Hackathon 2026
echo   Team: Alchemy
echo  ======================================
echo.

:: 1. Start backend
echo [1/2] Starting FastAPI backend (port 8080)...
start "THEMIS Backend" cmd /k "conda activate themis && uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload"

timeout /t 3 /nobreak >nul

:: 2. Start frontend
echo [2/2] Starting Vite frontend (port 3000)...
start "THEMIS Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo  ✅ THEMIS is starting up!
echo.
echo  Frontend:  http://localhost:3000
echo  Backend:   http://localhost:8080
echo  API Docs:  http://localhost:8080/api/docs
echo.
echo  NOTE: Make sure your SSH tunnel is open for cloud vLLM:
echo  ssh -N -L 8000:localhost:8000 root@^<cloud-ip^> -p ^<ssh-port^>
echo.
pause
