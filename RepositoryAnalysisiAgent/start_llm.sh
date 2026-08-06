#!/usr/bin/env bash
# Start the vLLM inference server for RepositoryAnalysisAgent on AMD W7900 (gfx1100).
#
# Environment variables:
#   ENFORCE_EAGER   "true" (default) | "false" — set false after M0 verifies graph mode
#   QUANT           "none" (default) | "fp8"   — set fp8 only if M1 verifies it works
#   MODEL_PATH      path to model dir (default: Qwen/Qwen2.5-Coder-14B-Instruct)
#   PORT            vLLM port (default: 8000)
#   TOOL_PARSER     "hermes" (default) | "qwen3_coder" etc — see vLLM supported list
set -euo pipefail

# ── ROCm stability env vars (gfx1100 known issues) ──
export PYTORCH_ROCM_ARCH="${PYTORCH_ROCM_ARCH:-gfx1100}"
export HSA_ENABLE_SDMA="${HSA_ENABLE_SDMA:-0}"
export AMD_SERIALIZE_KERNEL="${AMD_SERIALIZE_KERNEL:-3}"
export AMD_SERIALIZE_COPY="${AMD_SERIALIZE_COPY:-3}"

MODEL_PATH="${MODEL_PATH:-Qwen/Qwen2.5-Coder-14B-Instruct}"
PORT="${PORT:-8000}"
TOOL_PARSER="${TOOL_PARSER:-hermes}"

# ── enforce_eager toggle ──
ENFORCE_EAGER="${ENFORCE_EAGER:-true}"
EAGER_FLAG=""
if [ "$ENFORCE_EAGER" = "true" ]; then
    EAGER_FLAG="--enforce-eager"
    echo "[start_llm] HIP graph disabled (--enforce-eager). ~10-20% slower but stable on gfx1100."
else
    echo "[start_llm] HIP graph ENABLED (no --enforce-eager). Requires M0-verified stability."
fi

# ── FP8 weight quantization toggle ──
QUANT="${QUANT:-none}"
QUANT_FLAG=""
MAX_LEN=32768
if [ "$QUANT" = "fp8" ]; then
    QUANT_FLAG="--quantization fp8"
    MAX_LEN=32768
    echo "[start_llm] FP8 weight quantization ENABLED. max_model_len=$MAX_LEN."
    echo "[start_llm] WARNING: FP8 on gfx1100 is UNVERIFIED. May fail or produce bad output."
else
    echo "[start_llm] FP16 weights. max_model_len=$MAX_LEN."
fi

echo "[start_llm] Starting vLLM: $MODEL_PATH on port $PORT"
echo "[start_llm] tool_call_parser=$TOOL_PARSER  enforce_eager=$ENFORCE_EAGER  quant=$QUANT"

exec vllm serve "$MODEL_PATH" \
    --dtype float16 \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization 0.88 \
    --enable-auto-tool-choice \
    --tool-call-parser "$TOOL_PARSER" \
    $EAGER_FLAG \
    $QUANT_FLAG \
    --port "$PORT"

# Usage:
#   bash start_llm.sh                          # defaults: eager + fp16 + hermes parser
#   ENFORCE_EAGER=false bash start_llm.sh      # try graph mode (after M0 verification)
#   QUANT=fp8 bash start_llm.sh                # try fp8 (after M1 verification)
#   TOOL_PARSER=qwen3_coder bash start_llm.sh   # alternative parser for Qwen
