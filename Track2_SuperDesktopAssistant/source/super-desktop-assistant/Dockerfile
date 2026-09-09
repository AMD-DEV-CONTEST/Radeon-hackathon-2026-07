# Super Desktop Assistant - Docker 部署
# 构建: docker build -t super-desktop-assistant .
# 运行: docker run -p 7860:7860 --env-file .env super-desktop-assistant

FROM python:3.12-slim

WORKDIR /app

# 系统依赖（edge-tts 等需要）
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    sox libsox-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（.env 不进镜像，通过 --env-file 注入；__pycache__ 等由 .dockerignore 排除）
COPY . .

# 创建数据目录并设置权限
RUN mkdir -p data/conversations outputs && chmod -R 755 data outputs

EXPOSE 7860

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860')" || exit 1

# Web 模式（默认，需 --web，否则 CLI 无 TTY 会 EOFError 崩溃）:
#   docker run -p 7860:7860 ... super-desktop-assistant
# CLI 模式（需 TTY）:
#   docker run -it ... super-desktop-assistant --cli
ENTRYPOINT ["python", "app.py"]
CMD ["--web", "--host", "0.0.0.0", "--port", "7860"]
