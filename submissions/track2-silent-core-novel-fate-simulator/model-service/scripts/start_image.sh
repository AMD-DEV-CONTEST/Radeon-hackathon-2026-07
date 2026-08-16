#!/usr/bin/env bash
set -euo pipefail

set -a
source /persistent/silent-core/config.env
set +a
export HF_HOME=/persistent/silent-core/cache/huggingface
# HF_ENDPOINT removed — uses huggingface.co by default
export IMAGE_MODEL_PATH=/persistent/silent-core/models/Z-Image-Turbo
export IMAGE_UNLOAD_AFTER_REQUEST=false
export IMAGE_MAX_INTERNAL_PIXELS=262144
export IMAGE_COMPILE_TRANSFORMER=false
export IMAGE_CPU_OFFLOAD=true
export GENERATED_IMAGE_DIR=/persistent/silent-core/generated/images
exec /opt/venv/bin/uvicorn image_service:app \
  --app-dir /persistent/silent-core/src \
  --host 127.0.0.1 \
  --port 8002
