#!/usr/bin/env bash
# Serve the open-source model on an AMD Radeon GPU via vLLM (ROCm).
#
# Run this ON the Radeon Cloud instance. It starts an OpenAI-compatible
# server that Radeon Sentinel's OpenAICompatibleModelClient talks to.
#
# Before running:
#   1. Activate the ROCm-enabled Python environment (PyTorch ROCm build + vLLM).
#   2. Set MODEL_ID below (HuggingFace repo or local path).
#   3. Tune GPU_MEMORY_UTILIZATION / MAX_MODEL_LEN / QUANTIZATION for your VRAM.
#
# Usage:
#   bash scripts/serve_vllm.sh
#   MODEL_ID=Qwen/Qwen2.5-7B-Instruct bash scripts/serve_vllm.sh

set -euo pipefail

# Default model: Qwen2.5-7B-Instruct (Track 2 compliant open-source model,
# well-supported on ROCm). Override with MODEL_ID=... for other sizes.
: "${MODEL_ID:=Qwen/Qwen2.5-7B-Instruct}"
: "${PORT:=8000}"
: "${GPU_MEMORY_UTILIZATION:=0.90}"
: "${MAX_MODEL_LEN:=8192}"
: "${QUANTIZATION:=}"        # set to awq/gptq/fp8 for the optimization bonus
: "${DTYPE:=auto}"

# Sanity: confirm we actually see an AMD GPU via ROCm.
if ! command -v rocm-smi >/dev/null 2>&1; then
  echo "WARNING: rocm-smi not found. This script must run on a ROCm-enabled host." >&2
else
  echo "=== ROCm devices ==="
  rocm-smi --showproductname || true
fi

ARGS=(
  --port "$PORT"
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
  --max-model-len "$MAX_MODEL_LEN"
  --dtype "$DTYPE"
  --trust-remote-code
)

if [ -n "$QUANTIZATION" ]; then
  ARGS+=(--quantization "$QUANTIZATION")
fi

echo "=== starting vLLM ==="
echo "MODEL_ID=$MODEL_ID  PORT=$PORT  MAX_MODEL_LEN=$MAX_MODEL_LEN  QUANT=${QUANTIZATION:-none}"

if command -v vllm >/dev/null 2>&1; then
  exec "$(command -v vllm)" serve "$MODEL_ID" "${ARGS[@]}"
fi

exec python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_ID" \
  "${ARGS[@]}"
