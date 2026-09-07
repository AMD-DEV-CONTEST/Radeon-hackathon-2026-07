#!/usr/bin/env bash
set -euo pipefail

set -a
source /persistent/silent-core/config.env
set +a
exec /persistent/silent-core/tools/llama.cpp/build-rocm/bin/llama-server \
  --model /persistent/silent-core/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  --alias silent-core/llm \
  --host 127.0.0.1 \
  --port 8001 \
  --api-key "$SILENT_CORE_INTERNAL_API_KEY" \
  --ctx-size 32768 \
  --parallel 2 \
  --gpu-layers all \
  --flash-attn on \
  --threads 16 \
  --reasoning off \
  --reasoning-format deepseek \
  --metrics
