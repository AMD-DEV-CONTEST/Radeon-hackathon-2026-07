#!/usr/bin/env bash
# =============================================================================
# start.sh — Intelligent Claim Agent 一键启动
#
# 用法:
#   1. 确保模型已下载（默认 /models，可用 MODEL_DIR 覆盖）
#   2. bash start.sh
#
# 环境变量（可覆盖）:
#   MODEL_DIR    模型目录   (默认 /models，脚本自动探测 /models 或 /workspace/models)
#   LLAMA_SERVER llama-server 路径 (默认 /opt/llama.cpp/llama-server，可覆盖)
#   PORT_LLM     大模型端口 (默认 8080)
#   PORT_CLAIM   理赔后端   (默认 8001)
#   PORT_UW      核保后端   (默认 8002)
#   PORT_WEB     Gradio     (默认 7865)
# =============================================================================
set -euo pipefail

# ---------- 1. 定位模型目录 ----------
if [[ -z "${MODEL_DIR:-}" ]]; then
  if [[ -d /models ]]; then MODEL_DIR=/models
  elif [[ -d /workspace/models ]]; then MODEL_DIR=/workspace/models
  else
    echo "[ERROR] 未找到模型目录，请设置 MODEL_DIR=/path/to/models"
    exit 1
  fi
fi
MODEL="$MODEL_DIR/Qwen3.6-27B-UD-Q8_K_XL.gguf"
MMPROJ="$MODEL_DIR/mmproj-BF16.gguf"

if [[ ! -f "$MODEL" ]]; then
  echo "[ERROR] 模型不存在: $MODEL"
  echo "       请下载 Qwen3.6-27B-UD-Q8_K_XL.gguf 到 $MODEL_DIR"
  exit 1
fi

# ---------- 2. 变量 ----------
LLAMA_SERVER="${LLAMA_SERVER:-/opt/llama.cpp/llama-server}"
PORT_LLM="${PORT_LLM:-8080}"
PORT_CLAIM="${PORT_CLAIM:-8001}"
PORT_UW="${PORT_UW:-8002}"
PORT_WEB="${PORT_WEB:-7865}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-/tmp/claim-agent-logs}"
mkdir -p "$LOG_DIR"

echo "=============================================="
echo " 模型: $MODEL"
echo " 大模型端口: $PORT_LLM"
echo " 理赔后端:   $PORT_CLAIM"
echo " 核保后端:   $PORT_UW"
echo " Gradio:     $PORT_WEB"
echo " 日志目录:   $LOG_DIR"
echo "=============================================="

# ---------- 3. 启动 llama-server ----------
echo "[1/4] 启动 llama-server (大模型)..."
"$LLAMA_SERVER" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  -ngl 99 \
  -c 163840 \
  -ctk q4_0 -ctv q4_0 \
  -fa on \
  --spec-type draft-mtp \
  -np 1 \
  --host 0.0.0.0 --port "$PORT_LLM" \
  > "$LOG_DIR/llama-server.log" 2>&1 &

echo "      等待模型加载 (约 15-30 秒)..."
for i in $(seq 1 60); do
  if curl -s "http://127.0.0.1:$PORT_LLM/health" | grep -q "ok\|OK"; then
    echo "      ✅ 大模型就绪"
    break
  fi
  sleep 2
done

# ---------- 4. 启动 Python 后端 ----------
PYTHON="${PYTHON:-python3}"
export MODEL_HOST=127.0.0.1 MODEL_PORT="$PORT_LLM"

echo "[2/4] 启动理赔后端 :$PORT_CLAIM..."
nohup env MODEL_HOST=127.0.0.1 MODEL_PORT="$PORT_LLM" \
  "$PYTHON" -u -m backend.main \
  > "$LOG_DIR/backend-claim.log" 2>&1 &

echo "[3/4] 启动核保后端 :$PORT_UW..."
nohup env MODEL_HOST=127.0.0.1 MODEL_PORT="$PORT_LLM" \
  "$PYTHON" -u -m underwriting.backend \
  > "$LOG_DIR/backend-uw.log" 2>&1 &

echo "[4/4] 启动 Gradio Web :$PORT_WEB..."
nohup env MODEL_HOST=127.0.0.1 MODEL_PORT="$PORT_LLM" \
  "$PYTHON" -u -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
import app as a
import threading
threading.Thread(target=a._warmup, daemon=True).start()
a.demo.queue(default_concurrency_limit=4)
a.demo.launch(server_name='0.0.0.0', server_port=$PORT_WEB, share=False)
" > "$LOG_DIR/gradio.log" 2>&1 &

echo ""
echo "=============================================="
echo " ✅ 全部服务已启动"
echo "    Gradio:  http://127.0.0.1:$PORT_WEB"
echo "    理赔:    http://127.0.0.1:$PORT_CLAIM/docs"
echo "    核保:    http://127.0.0.1:$PORT_UW/docs"
echo "    日志:    $LOG_DIR"
echo " 停止: bash stop.sh"
echo "=============================================="
