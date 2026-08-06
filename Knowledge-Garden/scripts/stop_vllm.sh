#!/bin/bash
# stop_vllm.sh — stop vLLM servers by port. Safe pattern (no self-match).
# Usage: bash scripts/stop_vllm.sh [port]   (omit port = stop all)
PORT="${1:-}"
if [ -n "$PORT" ]; then
  echo "[stop_vllm] stopping server on :$PORT"
  pkill -f "openai.api_serve[r].*--port $PORT" 2>/dev/null || true
else
  echo "[stop_vllm] stopping all vLLM servers"
  pkill -f 'openai.api_serve[r]' 2>/dev/null || true
fi
sleep 2
echo "[stop_vllm] done"
