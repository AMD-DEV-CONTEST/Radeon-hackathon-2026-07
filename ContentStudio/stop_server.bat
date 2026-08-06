@echo off
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /PID %%a
echo Server stopped (port 8000 free).
timeout /t 2 >nul