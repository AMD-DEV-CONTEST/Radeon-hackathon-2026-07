@echo off
cd /d "C:\Users\VPX01\Documents\Default Project"
echo Starting Content Studio... open http://127.0.0.1:8000
".venv-paddle\Scripts\python.exe" -m uvicorn content_studio.web.app:app --host 127.0.0.1 --port 8000
echo.
echo Server stopped. If an error is shown above, screenshot it.
pause