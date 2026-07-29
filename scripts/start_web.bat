@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo === PrivateLocalAgent · Web Demo ===
echo Open after boot:  http://127.0.0.1:7900
echo Guide: START_HERE.md
echo.

if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
  pip install -q Pillow rapidocr-onnxruntime
) else (
  call .venv\Scripts\activate.bat
)

set HTTP_HOST=127.0.0.1
set HTTP_PORT=7900
set PLA_ALLOW_PUBLIC=0

start "" http://127.0.0.1:7900
python scripts\web_http_demo.py
