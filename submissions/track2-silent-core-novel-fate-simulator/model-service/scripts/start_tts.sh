#!/usr/bin/env bash
set -euo pipefail

set -a
source /persistent/silent-core/config.env
set +a
export HF_HOME=/persistent/silent-core/cache/huggingface
# HF_ENDPOINT removed — uses huggingface.co by default
export TTS_MODEL_PATH=/persistent/silent-core/models/Kokoro-82M
export TTS_ONNX_MODEL_PATH=/persistent/silent-core/models/kokoro-int8-multi-lang-v1_0-git
export TTS_BACKEND=torch
export TTS_DEVICE=cpu
export TTS_NUM_THREADS=16
export TTS_WARM_ON_START=true
export PYTHONPATH=/persistent/silent-core/venvs/tts-onnx/lib/python3.12/site-packages:${PYTHONPATH:-}
exec /opt/venv/bin/uvicorn tts_service:app \
  --app-dir /persistent/silent-core/src \
  --host 127.0.0.1 \
  --port 8003
