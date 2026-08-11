# 🦞 Union·由你 — CNC AI 工艺大脑 v11.0-AutoAdapt-tools
# Docker 构建文件
# 构建: docker build -t union-cnc-brain .
# 运行: docker run -d -p 7861:7861 --name union-cnc union-cnc-brain
#
# 注意: Ollama 默认连接宿主机 localhost:11434
# 如 Ollama 在宿主机，运行时加: --network host
# 如 Ollama 在容器内，使用 docker-compose.yml

FROM python:3.10-slim

LABEL maintainer="timo.cao <miscdd@163.com>"
LABEL description="Union·由你 CNC AI 工艺大脑 — 离线串行多专家决策系统"
LABEL version="11.0.0-AutoAdapt-tools"

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 项目文件
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 端口
EXPOSE 7861

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:7861/api/status || exit 1

# 启动
CMD ["python", "app/main.py"]
