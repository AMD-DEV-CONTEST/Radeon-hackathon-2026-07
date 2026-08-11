import os
import sys

# 显式设置环境变量
os.environ["TOT_ENABLED"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

# 切换到项目目录
project_dir = r"C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain"
os.chdir(project_dir)
sys.path.insert(0, project_dir)

# 启动 uvicorn
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=7862, log_level="info")