#!/usr/bin/env bash
# Start SparkFencer WebUI against Radeon Cloud's shared OpenAI-compatible APIs.
# Source a private environment file first; do not store API keys in this repo.
set -euo pipefail

: "${RADEON_API_KEY:?Set RADEON_API_KEY in a private environment file}"
: "${WEBUI_USER:?Set WEBUI_USER before exposing the WebUI}"
: "${WEBUI_PASSWORD:?Set WEBUI_PASSWORD before exposing the WebUI}"

export SPARKFENCER_ALLOW_RADEON_CLOUD_API=1
export VLM_BASE_URL="https://developer.amd.com.cn/radeon/api/v1"
export VLM_MODEL="Qwen3.6-35B-A3B"
export VLM_API_KEY="$RADEON_API_KEY"
export AGENT_MODEL="DeepSeek-V4-Flash"
export WEBUI_HOST="127.0.0.1"
export WEBUI_PORT="7860"

exec .venv/bin/python webui/app.py
