#!/bin/bash
# Post-training deployment script.
# Run after QLoRA training completes.
#
# 1. Merges LoRA adapter into base model
# 2. Starts vLLM serving the merged model
# 3. Starts the Gradio chat UI
# 4. Runs end-to-end verification
#
# Usage:
#   bash training/scripts/deploy.sh

set -euo pipefail

PYTHON="${VENV_PYTHON:-/opt/venv/bin/python}"
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo "============================================"
echo "  Post-Training Deployment"
echo "============================================"

# --- Find model paths ---
BASE_MODEL=$(ls -d models/hf_cache/models--Qwen--Qwen2.5-7B-Instruct/snapshots/*/ 2>/dev/null | head -1)
ADAPTER_PATH="models/qwen-trader-lora/final"
MERGED_PATH="models/qwen-trader-merged"

if [ -z "${BASE_MODEL}" ]; then
    echo "ERROR: Base model not found in models/hf_cache/"
    exit 1
fi

echo "Base model:  ${BASE_MODEL}"
echo "Adapter:     ${ADAPTER_PATH}"
echo "Merged output: ${MERGED_PATH}"

# --- Check if training completed ---
if [ ! -d "${ADAPTER_PATH}" ]; then
    echo "ERROR: LoRA adapter not found at ${ADAPTER_PATH}"
    echo "Has training completed? Check training/train_output.log"
    exit 1
fi

echo ""
echo "[1/4] Merging LoRA weights..."
${PYTHON} training/scripts/merge_lora.py \
    --base-model "${BASE_MODEL}" \
    --adapter-path "${ADAPTER_PATH}" \
    --output-path "${MERGED_PATH}"

echo ""
echo "[2/4] Starting vLLM server on port 8000..."
# Kill any existing vLLM
fuser -k 8000/tcp 2>/dev/null || true
sleep 2

export ROCBLAS_USE_HIPBLASLT=1
export HIP_VISIBLE_DEVICES=0
export VLLM_USE_TRITON_FLASH_ATTN=0

nohup ${PYTHON} -m vllm.entrypoints.openai.api_server \
    --model "${MERGED_PATH}" \
    --port 8000 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.50 \
    --dtype float16 \
    --trust-remote-code \
    --enforce-eager \
    > /tmp/vllm.log 2>&1 &

VLLM_PID=$!
echo "vLLM PID: ${VLLM_PID}"

# Wait for vLLM to be ready
echo "Waiting for vLLM to start..."
for i in $(seq 1 60); do
    if curl -s http://localhost:8000/v1/models | grep -q "data"; then
        echo "vLLM is ready!"
        break
    fi
    sleep 5
    echo "  Waiting... (${i}/60)"
done

echo ""
echo "[3/4] Starting Gradio chat UI on port 7860..."
fuser -k 7860/tcp 2>/dev/null || true
sleep 1

export VLLM_BASE_URL="http://localhost:8000/v1"
export BACKTEST_API_URL="http://localhost:8080"
export MODEL_NAME="${MERGED_PATH}"

nohup ${PYTHON} src/chat_app.py > /tmp/gradio.log 2>&1 &
GRADIO_PID=$!
echo "Gradio PID: ${GRADIO_PID}"

sleep 5
echo ""
echo "[4/4] Verifying services..."
echo "  vLLM:    $(curl -s http://localhost:8000/v1/models | head -1)"
echo "  API:     $(curl -s http://localhost:8080/health)"
echo "  Gradio:  $(curl -sI http://localhost:7860 | head -1)"

echo ""
echo "============================================"
echo "  Deployment Complete!"
echo "============================================"
echo ""
echo "Services:"
echo "  - Gradio Chat:  http://localhost:7860"
echo "  - vLLM API:     http://localhost:8000/v1"
echo "  - Backtest API: http://localhost:8080/docs"
echo ""
echo "To stop: kill ${VLLM_PID} ${GRADIO_PID}"
