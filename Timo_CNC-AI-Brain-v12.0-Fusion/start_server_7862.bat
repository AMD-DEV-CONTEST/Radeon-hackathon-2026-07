@echo off
cd /d "C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain"
set TOT_ENABLED=1
set PYTHONUNBUFFERED=1
"C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 7862 > "C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain\server_7862.log" 2>&1