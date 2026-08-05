#!/usr/bin/env bash
set -euo pipefail

eval "$(python3 -m privateops.rocm_profile)"

command -v rocminfo >/dev/null || { echo "rocminfo is required; choose a ROCm Radeon Cloud image." >&2; exit 1; }
command -v vllm >/dev/null || { echo "vllm is required in the selected cloud image." >&2; exit 1; }

rocminfo | sed -n '1,80p'
exec vllm serve "$PRIVATEOPS_MODEL_NAME" \
  --host "$PRIVATEOPS_MODEL_HOST" \
  --port "$PRIVATEOPS_MODEL_PORT" \
  --dtype auto \
  --max-model-len "$PRIVATEOPS_MAX_MODEL_LEN" \
  --gpu-memory-utilization "$PRIVATEOPS_GPU_MEMORY_UTILIZATION"
