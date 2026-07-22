#!/usr/bin/env bash
set -euo pipefail

model_dir="${1:-models/qwen3-8b}"
vllm_bin="${VLLM_BIN:-vllm}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$repo_root/scripts/prepare_radeon_vllm.sh"

if [[ ! -f "$model_dir/config.json" ]]; then
  echo "Model directory is incomplete: $model_dir" >&2
  exit 1
fi
if ! command -v "$vllm_bin" >/dev/null 2>&1; then
  echo "vLLM executable is unavailable: $vllm_bin" >&2
  exit 1
fi

exec "$vllm_bin" serve "$model_dir" \
  --served-model-name signalforge-qwen3-8b-bf16 \
  --host "${SIGNALFORGE_MODEL_HOST:-127.0.0.1}" \
  --port "${SIGNALFORGE_MODEL_PORT:-8000}" \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.80 \
  --max-num-seqs 8 \
  --attention-backend ROCM_ATTN \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --disable-log-requests
