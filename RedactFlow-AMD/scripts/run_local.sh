#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export REDACTFLOW_DATA_DIR="${REDACTFLOW_DATA_DIR:-$PROJECT_DIR/data}"
export LOCAL_LLM_ENABLED="${LOCAL_LLM_ENABLED:-0}"
export LOCAL_LLM_URL="${LOCAL_LLM_URL:-http://127.0.0.1:8080/v1}"
export LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-qwen2.5-7b-instruct}"

exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-7860}"
