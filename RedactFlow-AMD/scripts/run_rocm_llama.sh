#!/usr/bin/env bash
set -euo pipefail

: "${LLAMA_SERVER:?Set LLAMA_SERVER to the ROCm-enabled llama-server binary}"
: "${MODEL_PATH:?Set MODEL_PATH to a local GGUF model}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-}"

exec "$LLAMA_SERVER" \
  --model "$MODEL_PATH" \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size "${CTX_SIZE:-8192}" \
  --n-gpu-layers "${GPU_LAYERS:-999}" \
  --flash-attn on \
  --parallel "${PARALLEL:-2}"

