#!/bin/bash
# Launch vLLM serving on the Radeon GPU instance.
set -e

MODEL="${MODEL_NAME:-Qwen/Qwen3-8B-Instruct}"
PORT="${VLLM_PORT:-8000}"

echo "Serving $MODEL on port $PORT ..."
vllm serve "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --download-dir "${HF_HOME:-/workspace/models}"
    # TODO: add --quantization / --gpu-memory-utilization flags after benchmarking
