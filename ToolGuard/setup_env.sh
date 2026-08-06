#!/bin/bash
# setup_env.sh
# Run this ONCE every time you launch a fresh Radeon Cloud instance:
#   source /persistent/Radeon-hackathon-2026-07/ToolGuard/setup_env.sh
#
# Purpose: point everything at /persistent (the storage that ACTUALLY
# survives a destroy+relaunch - confirmed Aug 1 2026, /workspace does NOT
# survive despite what we originally assumed) instead of /workspace or
# the instance's local disk.

# --- Hugging Face model cache -> persistent, not /workspace, not local disk ---
export HF_HUB_CACHE=/persistent/hf_cache

# --- vLLM compiled-graph cache -> also persistent, avoids full rebuild each launch ---
export VLLM_CACHE_ROOT=/persistent/vllm_cache
mkdir -p "$VLLM_CACHE_ROOT"

# --- Make sure the ROCm venv is on PATH for this shell ---
export PATH="/opt/venv/bin:$PATH"

echo "[setup_env] HF_HUB_CACHE=$HF_HUB_CACHE"
echo "[setup_env] VLLM_CACHE_ROOT=$VLLM_CACHE_ROOT"
echo "[setup_env] Done. Next: apt update && apt install -y tmux, then start vLLM in tmux."
