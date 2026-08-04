#!/usr/bin/env bash
# Capture all three benchmark profiles on the Radeon instance.
set -uo pipefail
PROJECT=/root/radeonpilot-project
LLAMA=/root/radeonpilot-setup/llama.cpp/build/bin/llama-server
PY=/root/radeonpilot/.venv/bin/python
cd "$PROJECT"

wait_ready() {
  for i in $(seq 1 60); do
    curl -s --max-time 3 http://127.0.0.1:8000/v1/models | grep -q qwen3-8b && return 0
    sleep 3
  done
  echo "endpoint did not come up" >&2
  return 1
}

restart() { # $1=model $2=parallel $3=flash-attn
  pkill -x llama-server 2>/dev/null
  sleep 4
  nohup "$LLAMA" --model "$1" --host 127.0.0.1 --port 8000 \
    --ctx-size 8192 --n-gpu-layers 99 \
    --parallel "$2" --flash-attn "$3" \
    --chat-template-kwargs '{"enable_thinking":false}' \
    --alias qwen3-8b > /root/radeonpilot-setup/llama-server.log 2>&1 &
  wait_ready || exit 1
}

echo "== profile baseline (F16, parallel 4, fa auto)"
restart /root/models/gguf/Qwen3-8B-f16.gguf 4 auto
VLLM_PID=$(pgrep -x llama-server | head -1) "$PY" scripts/benchmark_vllm.py --profile baseline --engine llama.cpp --runs 3

echo "== profile optimized (F16, parallel 8, fa on)"
restart /root/models/gguf/Qwen3-8B-f16.gguf 8 on
VLLM_PID=$(pgrep -x llama-server | head -1) "$PY" scripts/benchmark_vllm.py --profile optimized --engine llama.cpp --runs 3

echo "== profile quantized (Q4_K_M, parallel 8, fa on)"
restart /root/models/gguf/Qwen3-8B-Q4_K_M.gguf 8 on
"$PY" scripts/run_quality_gate.py || echo "QUALITY GATE FAILED"
VLLM_PID=$(pgrep -x llama-server | head -1) "$PY" scripts/benchmark_vllm.py --profile quantized --engine llama.cpp --runs 3

echo "== leaving endpoint on quantized+optimized config"
ls -la benchmarks/results/
echo BENCH_ALL_DONE
