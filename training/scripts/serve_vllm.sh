#!/bin/bash
# Start vLLM serving on AMD ROCm GPU.
#
# Serves the merged Qwen2.5-7B model with OpenAI-compatible API.
# Dify connects to this endpoint as an "OpenAI-API-compatible" provider.
#
# Usage:
#   bash training/scripts/serve_vllm.sh [MODEL_PATH]
#
# Default model path: models/qwen-trader-merged

set -euo pipefail

MODEL_PATH="${1:-models/qwen-trader-merged}"
PORT="${VLLM_PORT:-8000}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-32768}"
GPU_UTIL="${VLLM_GPU_UTIL:-0.45}"
SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-models/qwen-trader-merged}"

echo "=== vLLM Serving on AMD ROCm ==="
echo "Model:  ${MODEL_PATH}"
echo "Port:   ${PORT}"
echo "Max len: ${MAX_MODEL_LEN}"
echo "GPU util: ${GPU_UTIL}"
echo "Served name: ${SERVED_MODEL_NAME}"
echo ""

# --- Check model exists ---
if [ ! -d "${MODEL_PATH}" ] && [ ! -f "${MODEL_PATH}/config.json" ]; then
    if [ ! -f "${MODEL_PATH}" ]; then
        echo "ERROR: Model not found at ${MODEL_PATH}"
        echo "Run training/scripts/merge_lora.py first, or pass a HuggingFace model name."
        echo ""
        echo "Usage: bash serve_vllm.sh [MODEL_PATH]"
        echo "  e.g., bash serve_vllm.sh Qwen/Qwen2.5-7B-Instruct"
        exit 1
    fi
fi

# --- ROCm environment variables ---
export ROCBLAS_USE_HIPBLASLT=1          # Critical for AWQ/performance
export HIP_VISIBLE_DEVICES=0            # Use GPU 0
export HSA_OVERRIDE_GFX_VERSION=""       # Auto-detect
export VLLM_USE_TRITON_FLASH_ATTN=0      # Use ROCm-native flash attention
export OMP_NUM_THREADS=8

# --- Check if vLLM is installed ---
VENV_PYTHON="${VENV_PYTHON:-/opt/venv/bin/python}"
if ! ${VENV_PYTHON} -c "import vllm" 2>/dev/null; then
    echo "vLLM not found. Installing..."
    ${VENV_PYTHON} -m pip install vllm --quiet
fi

echo "Starting vLLM server..."
echo "API will be available at: http://localhost:${PORT}/v1"
echo ""

# --- Start vLLM ---
exec ${VENV_PYTHON} -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_PATH}" \
    --served-model-name "${SERVED_MODEL_NAME}" \
    --port "${PORT}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${GPU_UTIL}" \
    --dtype float16 \
    --trust-remote-code \
    --enforce-eager
