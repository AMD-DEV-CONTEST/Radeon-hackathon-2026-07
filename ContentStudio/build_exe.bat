@echo off
cd /d "C:\Users\VPX01\Documents\Default Project"
".venv-paddle\Scripts\pyinstaller.exe" ^
  --noconfirm ^
  --windowed ^
  --name ContentStudio ^
  --add-data "content_studio\web\templates;content_studio\web\templates" ^
  --add-data "content_studio\styles\workflows;content_studio\styles\workflows" ^
  --collect-all uvicorn ^
  --collect-all fastapi ^
  --collect-all starlette ^
  --collect-all pydantic ^
  --collect-all jinja2 ^
  --collect-all python_multipart ^
  --collect-all pillow_heif ^
  --hidden-import webview.platforms.edgechromium ^
  --exclude-module paddle ^
  --exclude-module paddleocr ^
  --exclude-module paddlex ^
  --exclude-module pandas ^
  --exclude-module modelscope ^
  --exclude-module cv2 ^
  --exclude-module customtkinter ^
  --exclude-module tkinter ^
  --exclude-module matplotlib ^
  --exclude-module scipy ^
  --exclude-module shapely ^
  --exclude-module pyclipper ^
  desktop_app.py
