FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

WORKDIR /app

COPY apps/api/requirements.txt /app/apps/api/requirements.txt
RUN pip install --upgrade pip \
    && pip install --retries 10 --timeout 120 -r /app/apps/api/requirements.txt

COPY packages/botclaw-spec /app/packages/botclaw-spec
RUN pip install --retries 10 --timeout 120 -e /app/packages/botclaw-spec/python

COPY apps/api /app/apps/api

RUN mkdir -p /data

WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
