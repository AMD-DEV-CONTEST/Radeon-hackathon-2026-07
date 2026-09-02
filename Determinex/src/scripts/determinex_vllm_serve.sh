#!/bin/bash
# determinex_vllm_serve.sh — production-grade local LLM serving via vLLM
#
# Replaces ollama for higher throughput / tensor parallelism.
# Auto-detects GPU count and applies appropriate sharding.
#
# Usage:
#   ./determinex_vllm_serve.sh determinex-engineer-v11-dsl       # serves on :8000
#   ./determinex_vllm_serve.sh --port 8001 determinex-sentinel-v5-dsl  # different port
#
# Requires: pip install vllm OR docker pull vllm/vllm-openai:latest

set -uo pipefail

MODEL_DIR="${DETERMINEX_MODELS_DIR:-T:/determinex-models}"
PORT=8000
MAX_LEN=8192

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --max-len) MAX_LEN="$2"; shift 2 ;;
        --models-dir) MODEL_DIR="$2"; shift 2 ;;
        *) MODEL="$1"; shift ;;
    esac
done

if [ -z "${MODEL:-}" ]; then
    echo "usage: $0 [--port N] [--max-len N] MODEL_NAME"
    echo "Available models:"
    ls "$MODEL_DIR" 2>/dev/null | head -20
    exit 1
fi

MODEL_PATH="$MODEL_DIR/$MODEL"
if [ ! -d "$MODEL_PATH" ]; then
    echo "ERROR: model not found at $MODEL_PATH"
    exit 1
fi

# GPU detection (NVIDIA only for now)
GPU_COUNT=$(nvidia-smi --list-gpus 2>/dev/null | wc -l || echo 0)
TP_SIZE=1
if [ "$GPU_COUNT" -gt 1 ]; then
    TP_SIZE="$GPU_COUNT"
fi

echo "=== Determinex vLLM Server ==="
echo "Model:           $MODEL"
echo "Path:            $MODEL_PATH"
echo "Port:            $PORT"
echo "Max length:      $MAX_LEN"
echo "GPUs:            $GPU_COUNT"
echo "Tensor parallel: $TP_SIZE"
echo

# Prefer docker (cleaner, GPU passthrough)
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    exec docker run --rm \
        --gpus "device=all" \
        --ipc host \
        -v "$MODEL_PATH:/model" \
        -p "$PORT:8000" \
        --name "determinex-vllm-$MODEL" \
        vllm/vllm-openai:latest \
        --model /model \
        --served-model-name "$MODEL" \
        --max-model-len "$MAX_LEN" \
        --tensor-parallel-size "$TP_SIZE" \
        --enable-prefix-caching \
        --gpu-memory-utilization 0.92
fi

# Fallback to pip-installed vLLM
if command -v vllm >/dev/null; then
    exec vllm serve "$MODEL_PATH" \
        --port "$PORT" \
        --served-model-name "$MODEL" \
        --max-model-len "$MAX_LEN" \
        --tensor-parallel-size "$TP_SIZE" \
        --enable-prefix-caching \
        --gpu-memory-utilization 0.92
fi

echo "ERROR: neither docker nor pip-installed vllm found"
echo "Install: pip install vllm  OR  docker pull vllm/vllm-openai"
exit 1
