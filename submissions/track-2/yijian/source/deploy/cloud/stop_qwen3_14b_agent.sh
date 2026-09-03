#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
PORT="${YIJIAN_QWEN3_14B_PORT:-8083}"
PID_FILE="$PERSIST_ROOT/qwen3-14b-agent-$PORT.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Qwen3-14B Agent没有登记运行中的进程。"
  exit 0
fi
pid="$(tr -dc '0-9' < "$PID_FILE")"
if [[ -z "$pid" || ! -d "/proc/$pid" ]]; then
  rm -f -- "$PID_FILE"
  echo "已清理过期PID文件。"
  exit 0
fi
cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
if [[ "$cmdline" != *"vllm"* || "$cmdline" != *"$PORT"* ]]; then
  echo "PID $pid 不是本脚本登记的vLLM进程，拒绝停止。" >&2
  exit 2
fi
kill "$pid"
for _ in $(seq 1 30); do
  [[ ! -d "/proc/$pid" ]] && break
  sleep 1
done
if [[ -d "/proc/$pid" ]]; then
  echo "vLLM进程未在30秒内退出，请人工检查PID $pid。" >&2
  exit 3
fi
rm -f -- "$PID_FILE"
echo "Qwen3-14B Agent已停止。"
