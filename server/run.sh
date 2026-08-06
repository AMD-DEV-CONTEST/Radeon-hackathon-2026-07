#!/usr/bin/env bash
# 启动后端 API（默认 8000 端口；ComfyUI 地址可用 COMFY_URL 覆盖）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
exec ComfyUI/.venv/bin/python -m uvicorn server.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
