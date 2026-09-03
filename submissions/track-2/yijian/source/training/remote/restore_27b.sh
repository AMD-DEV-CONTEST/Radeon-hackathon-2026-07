#!/usr/bin/env bash
set -euo pipefail

SERVER=/persistent/yijian/llama.cpp/build/bin/llama-server
MODEL=/persistent/yijian/models/qwen36/Qwen3.6-27B-Q4_K_M.gguf
LOG=/persistent/yijian/logs/qwen36-27b-mentor-8082.log

if pgrep -f "llama-server.*--port 8082" >/dev/null; then
  echo "27B service is already running"
  exit 0
fi

nohup "$SERVER" \
  --model "$MODEL" \
  --alias Yijian-Qwen3.6-27B-GoCoach \
  --host 127.0.0.1 --port 8082 --ctx-size 8192 --parallel 1 \
  --n-gpu-layers 99 --flash-attn on --no-ui \
  >> "$LOG" 2>&1 &

for _ in $(seq 1 180); do
  if curl -fsS --max-time 2 http://127.0.0.1:8082/health >/dev/null; then
    echo "27B service restored"
    exit 0
  fi
  sleep 1
done

echo "27B process started but health check did not pass within 180 seconds" >&2
exit 1
