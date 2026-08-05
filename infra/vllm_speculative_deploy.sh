#!/bin/bash
# THEMIS — AMD ROCm Speculative Decoding Deployment Script
# Target GPU: AMD Radeon PRO W7900D (48GB GDDR6 VRAM)
# ROCm Stack: 7.2.1 | Engine: vLLM 0.16.1.dev0 (Legacy V0 engine for speculative support)

set -e

echo "=== THEMIS ROCm Speculative Decoding Deployment ==="

# 1. Environment variables for AMD Flash Attention & legacy engine
export VLLM_ATTENTION_BACKEND=ROCM_AITER_FA
export VLLM_USE_V1=0
export ROCM_PATH=/opt/rocm

# 2. Check ROCm GPU Status
if command -v rocm-smi &> /dev/null; then
    echo "🟢 AMD GPU Status:"
    rocm-smi --showid --showuse --showmeminfo vram
else
    echo "⚠️ rocm-smi not found. Continuing..."
fi

# 3. Model Paths (Cached on PVC)
MAIN_MODEL="${MAIN_MODEL:-Qwen/Qwen2.5-Coder-32B-Instruct-AWQ}"
DRAFT_MODEL="${DRAFT_MODEL:-Qwen/Qwen2.5-Coder-1.5B-Instruct}"
PORT="${PORT:-8000}"

echo "🚀 Launching vLLM with Speculative Draft Model:"
echo "   Main Model:  $MAIN_MODEL"
echo "   Draft Model: $DRAFT_MODEL"
echo "   Port:        $PORT"

python3 -m vllm.entrypoints.openai.api_server \
  --model "$MAIN_MODEL" \
  --speculative-model "$DRAFT_MODEL" \
  --num-speculative-tokens 5 \
  --quantization awq \
  --max-model-len 65536 \
  --gpu-memory-utilization 0.80 \
  --enable-chunked-prefill \
  --speculative-config '{"method": "draft_model", "num_speculative_tokens": 5}' \
  --port "$PORT" \
  --host 0.0.0.0
