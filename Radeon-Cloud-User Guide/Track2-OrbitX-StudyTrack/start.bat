@echo off
set "ROOT=%~dp0"
start "StudyTrack Backend" cmd /k "pushd "%ROOT%backend" && python -m flask --app app run"
start "StudyTrack Frontend" cmd /k "pushd "%ROOT%frontend" && npm run dev -- --host 0.0.0.0"
timeout /t 6 >nul
if not "%FRONTEND_URL%"=="" start "" "%FRONTEND_URL%"
