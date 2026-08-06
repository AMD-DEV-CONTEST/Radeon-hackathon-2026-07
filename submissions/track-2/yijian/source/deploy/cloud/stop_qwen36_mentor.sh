#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
PORT="${YIJIAN_QWEN36_MODEL_PORT:-8082}"
PID_FILE="$PERSIST_ROOT/qwen36-27b-mentor-$PORT.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Qwen3.6 27B PID文件不存在；视为已停止。"
  exit 0
fi
pid="$(tr -cd '0-9' < "$PID_FILE")"
[[ -n "$pid" ]] || { echo "27B PID文件无效：$PID_FILE" >&2; exit 2; }
if ! kill -0 "$pid" 2>/dev/null; then
  rm -f -- "$PID_FILE"
  echo "Qwen3.6 27B进程已不存在。"
  exit 0
fi
command_line="$(ps -p "$pid" -o args= || true)"
if [[ "$command_line" != *"llama-server"* || "$command_line" != *"Qwen3.6-27B-Q4_K_M.gguf"* ]]; then
  echo "PID $pid 不是预期27B llama-server，拒绝停止：$command_line" >&2
  exit 3
fi
kill "$pid"
for _ in $(seq 1 60); do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f -- "$PID_FILE"
    echo "Qwen3.6 27B已安全停止。"
    exit 0
  fi
  sleep 1
done
echo "Qwen3.6 27B在60秒内未退出；未发送强制信号。" >&2
exit 4
