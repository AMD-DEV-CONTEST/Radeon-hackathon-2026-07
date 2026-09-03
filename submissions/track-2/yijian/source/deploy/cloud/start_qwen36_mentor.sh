#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
SERVER="$PERSIST_ROOT/llama.cpp/build/bin/llama-server"
MODEL="${YIJIAN_QWEN36_MODEL_PATH:-$PERSIST_ROOT/models/qwen36/Qwen3.6-27B-Q4_K_M.gguf}"
ALIAS="${YIJIAN_QWEN36_MODEL_ALIAS:-Yijian-Qwen3.6-27B-GoCoach}"
PORT="${YIJIAN_QWEN36_MODEL_PORT:-8082}"
LOG="$PERSIST_ROOT/logs/qwen36-27b-mentor-$PORT.log"
PID_FILE="$PERSIST_ROOT/qwen36-27b-mentor-$PORT.pid"

[[ -x "$SERVER" ]] || { echo "llama-server 尚未构建：$SERVER"; exit 1; }
[[ -f "$MODEL" ]] || { echo "Qwen3.6-27B 尚未下载：$MODEL"; exit 1; }
mkdir -p "$PERSIST_ROOT/logs"

if curl -fsS "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -Fq "$ALIAS"; then
  echo "Qwen3.6 围棋导师已在 $PORT 端口运行"
  exit 0
fi
if curl -fsS "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
  echo "$PORT 端口正被另一模型占用；请先在验收后切换服务" >&2
  exit 2
fi

nohup "$SERVER" \
  --model "$MODEL" \
  --alias "$ALIAS" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --ctx-size 8192 \
  --parallel 1 \
  --n-gpu-layers 99 \
  --flash-attn on \
  --no-ui \
  >"$LOG" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 180); do
  if curl -fsS "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -Fq "$ALIAS"; then
    echo "Qwen3.6 围棋导师已就绪：$ALIAS"
    exit 0
  fi
  sleep 1
done

tail -100 "$LOG" >&2 || true
echo "Qwen3.6 围棋导师未能在 180 秒内就绪" >&2
exit 1
