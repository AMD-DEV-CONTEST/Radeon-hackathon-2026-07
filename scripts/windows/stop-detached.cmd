@echo off
taskkill /FI "WINDOWTITLE eq botversex-api*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq botversex-realtime*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq botversex-web*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq botversex-watchdog*" /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8002" ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>&1
echo BotverseX stopped.
