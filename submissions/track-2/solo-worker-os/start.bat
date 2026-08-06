@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "start.ps1"
pause
