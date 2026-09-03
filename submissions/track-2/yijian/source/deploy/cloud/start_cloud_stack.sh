#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
LLAMA_SERVER="$PERSIST_ROOT/llama.cpp/build/bin/llama-server"
VENV="$PERSIST_ROOT/venv"
HF_HOME="${HF_HOME:-$PERSIST_ROOT/huggingface}"
LOG_DIR="$PERSIST_ROOT/logs"
export HF_HOME

[[ -x "$LLAMA_SERVER" ]] || { echo "请先运行 install_cloud_runtime.sh"; exit 1; }
CLOUD_MODEL_PATH="$PERSIST_ROOT/models/qwen36/Qwen3.6-27B-Q4_K_M.gguf"
LOCAL_MODEL_PATH="$(find "$HF_HOME/models--Qwen--Qwen3-4B-GGUF" -type f -name '*Q4_K_M*.gguf' 2>/dev/null | sort | head -n 1 || true)"
[[ -f "$CLOUD_MODEL_PATH" ]] || { echo "未找到 Qwen3.6-27B Q4，请先运行安装脚本"; exit 1; }
[[ -f "$LOCAL_MODEL_PATH" ]] || { echo "未找到 Qwen3-4B Q4，请先运行安装脚本"; exit 1; }
mkdir -p "$LOG_DIR"

if ! curl -fsS http://127.0.0.1:8081/v1/models >/dev/null 2>&1; then
  echo "启动 W7900 上的 4B 基准老师..."
  nohup "$LLAMA_SERVER" \
    --model "$LOCAL_MODEL_PATH" \
    --alias Qwen3-4B-Q4_K_M --host 127.0.0.1 --port 8081 \
    --ctx-size 4096 --parallel 1 --n-gpu-layers 99 \
    >"$LOG_DIR/local-4b.log" 2>&1 &
  echo $! > "$PERSIST_ROOT/local-4b.pid"
fi

if ! curl -fsS http://127.0.0.1:8082/v1/models >/dev/null 2>&1; then
  echo "启动 W7900 云端围棋老师..."
  nohup "$LLAMA_SERVER" \
    --model "$CLOUD_MODEL_PATH" \
    --alias Yijian-Qwen3.6-27B-GoCoach --host 127.0.0.1 --port 8082 \
    --ctx-size 8192 --parallel 1 --n-gpu-layers 99 --flash-attn on \
    >"$LOG_DIR/cloud-llm.log" 2>&1 &
  echo $! > "$PERSIST_ROOT/cloud-llm.pid"
fi

for _ in $(seq 1 180); do
  curl -fsS http://127.0.0.1:8081/v1/models >/dev/null 2>&1 && \
    curl -fsS http://127.0.0.1:8082/v1/models >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8081/v1/models >/dev/null
curl -fsS http://127.0.0.1:8082/v1/models >/dev/null

export YIJIAN_CLOUD_LLM_URL="http://127.0.0.1:8082/v1"
export YIJIAN_CLOUD_LLM_MODEL="Yijian-Qwen3.6-27B-GoCoach"
export YIJIAN_LOCAL_LLM_URL="http://127.0.0.1:8081/v1"
export YIJIAN_LOCAL_LLM_MODEL="Qwen3-4B-Q4_K_M"
cd "$PROJECT_ROOT/backend"
exec "$VENV/bin/python" -m uvicorn app:app --host 0.0.0.0 --port 8600
