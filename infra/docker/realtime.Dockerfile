FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ python3-dev linux-libc-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# torch CPU-only from PyTorch index; pin <2.11 for lerobot compat
RUN pip install --retries 10 --timeout 300 \
    "torch>=2.2.0,<2.11.0" "torchvision>=0.17.0,<0.26.0" \
    --index-url https://download.pytorch.org/whl/cpu

COPY apps/realtime/requirements.txt /app/apps/realtime/requirements.txt
COPY packages/botclaw-spec/python/pyproject.toml /app/packages/botclaw-spec/python/pyproject.toml

RUN pip install --retries 10 --timeout 120 -r /app/apps/realtime/requirements.txt

# 再拷代码
COPY apps/realtime /app/apps/realtime
COPY packages/botclaw-spec /app/packages/botclaw-spec

# 安装本地 botclaw-spec (editable)
RUN pip install --retries 10 --timeout 120 -e /app/packages/botclaw-spec/python

WORKDIR /app/apps/realtime
EXPOSE 8002
# Container nginx talks to realtime over plain HTTP on the internal network.
# HTTPS self-signed mode is for end-user Local Agent installs only.
CMD ["python", "run_api.py", "--http"]
