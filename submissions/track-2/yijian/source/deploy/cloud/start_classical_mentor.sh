#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
SERVER="$PERSIST_ROOT/llama.cpp/build/bin/llama-server"
MODEL="$PERSIST_ROOT/models/gguf/qwen3-4b-classical-v2-q4_k_m.gguf"
ALIAS="${YIJIAN_CLASSICAL_MODEL_ALIAS:-Yijian-Qwen3-4B-Classical-Go}"
PORT="${YIJIAN_CLASSICAL_MODEL_PORT:-8082}"
LOG="$PERSIST_ROOT/logs/classical-mentor.log"
PID_FILE="$PERSIST_ROOT/classical-mentor.pid"

[[ -x "$SERVER" ]] || { echo "llama-server 尚未构建：$SERVER"; exit 1; }
[[ -f "$MODEL" ]] || { echo "古典围棋模型尚未导出：$MODEL"; exit 1; }
mkdir -p "$PERSIST_ROOT/logs"

if curl -fsS "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
  echo "古典围棋导师已在 $PORT 端口运行"
  exit 0
fi

nohup "$SERVER" \
  --model "$MODEL" \
  --alias "$ALIAS" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --ctx-size 4096 \
  --parallel 1 \
  --n-gpu-layers 99 \
  --no-ui \
  >"$LOG" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    echo "古典围棋导师已就绪：$ALIAS"
    exit 0
  fi
  sleep 1
done

tail -80 "$LOG" >&2 || true
echo "古典围棋导师未能在 90 秒内就绪" >&2
exit 1
