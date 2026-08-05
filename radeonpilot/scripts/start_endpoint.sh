#!/usr/bin/env bash
# Launch the local OpenAI-compatible model endpoint on the Radeon GPU.
# Usage:
#   ENGINE=vllm   bash scripts/start_endpoint.sh   (Qwen3-8B BF16 via vLLM)
#   ENGINE=llama  bash scripts/start_endpoint.sh   (Q4_K_M GGUF via llama-server)
set -euo pipefail

ENGINE="${ENGINE:-llama}"
MODEL_DIR="${MODEL_DIR:-/root/models/Qwen3-8B}"
GGUF="${GGUF:-/root/models/gguf/Qwen3-8B-Q4_K_M.gguf}"
LLAMA_SERVER="${LLAMA_SERVER:-/root/radeonpilot-setup/llama.cpp/build/bin/llama-server}"
VLLM_PYTHON="${VLLM_PYTHON:-/root/radeonpilot/.venv-vllm/bin/python}"
HOST=127.0.0.1
PORT="${PORT:-8000}"

if [ "$ENGINE" = "vllm" ]; then
  echo "Starting vLLM endpoint on ${HOST}:${PORT} (BF16)..."
  exec "$VLLM_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_DIR" \
    --served-model-name qwen3-8b \
    --host "$HOST" --port "$PORT" \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.85 \
    --enable-prefix-caching \
    --enable-chunked-prefill
elif [ "$ENGINE" = "llama" ]; then
  echo "Starting llama.cpp endpoint on ${HOST}:${PORT} (GGUF)..."
  exec "$LLAMA_SERVER" \
    --model "$GGUF" \
    --host "$HOST" --port "$PORT" \
    --ctx-size 16384 \
    --n-gpu-layers 99 \
    --parallel "${PARALLEL:-4}" \
    --flash-attn "${FLASH_ATTN:-auto}" \
    --chat-template-kwargs '{"enable_thinking":false}' \
    --alias qwen3-8b
else
  echo "Unknown ENGINE '$ENGINE' (use vllm or llama)" >&2
  exit 1
fi
