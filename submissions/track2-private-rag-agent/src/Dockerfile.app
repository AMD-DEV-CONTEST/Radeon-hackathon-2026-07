# ============================================================
# Dockerfile.app — Agent 应用镜像（docker compose 用）
#
# 轻量 Python 镜像，只跑 Agent 应用，推理走容器网络的 Ollama 服务：
#   build:  docker compose up -d --build
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# 解析文档用的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 首次启动等待 Ollama 就绪后拉起网页界面
CMD ["python", "main.py", "ui"]
