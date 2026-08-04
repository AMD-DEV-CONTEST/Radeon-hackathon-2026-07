#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${project_root}/ops/radeon/policyseal-env.sh"

model_dir="${POLICYSEAL_MODEL_DIR:-/workspace/models/Qwen3-8B}"
served_model="${POLICYSEAL_LLM_MODEL:-Qwen/Qwen3-8B}"
port="${POLICYSEAL_LLM_PORT:-8000}"

if [[ ! -f "${model_dir}/model.safetensors.index.json" ]]; then
  echo "Qwen3-8B model files are incomplete at ${model_dir}." >&2
  exit 1
fi

# The official image ships a CUDA-importing flash_attn initializer beside ROCm Triton code.
export PYTHONPATH="${project_root}/ops/radeon/compat${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export VLLM_ROCM_USE_AITER="${VLLM_ROCM_USE_AITER:-0}"

exec /opt/venv/bin/vllm serve "${model_dir}" \
  --served-model-name "${served_model}" \
  --host 127.0.0.1 \
  --port "${port}" \
  --dtype bfloat16 \
  --attention-backend TRITON_ATTN \
  --max-model-len 8192 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.46 \
  --generation-config vllm \
  --enforce-eager \
  --disable-log-requests
