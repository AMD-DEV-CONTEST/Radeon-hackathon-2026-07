#!/usr/bin/env bash
set -euo pipefail

# Inference-only optimizations validated on AMD gfx1100. The residual-clone
# experiment is intentionally disabled because it produced no latency benefit.
export SMOLVLA_ATTENTION_BACKEND="${SMOLVLA_ATTENTION_BACKEND:-sdpa_auto}"
export SMOLVLA_OPTIMIZE_LOOP="${SMOLVLA_OPTIMIZE_LOOP:-1}"
export SMOLVLA_OPTIMIZE_RESIDUAL="${SMOLVLA_OPTIMIZE_RESIDUAL:-0}"
export SMOLVLA_CACHE_LANGUAGE="${SMOLVLA_CACHE_LANGUAGE:-1}"
export SMOLVLA_CACHE_MODEL_LAYERS="${SMOLVLA_CACHE_MODEL_LAYERS:-1}"
export SMOLVLA_LIGHTWEIGHT_OUTPUT="${SMOLVLA_LIGHTWEIGHT_OUTPUT:-1}"
export SMOLVLA_USE_INFERENCE_MODE="${SMOLVLA_USE_INFERENCE_MODE:-1}"
export SMOLVLA_CACHE_DENOISE_LAYOUT="${SMOLVLA_CACHE_DENOISE_LAYOUT:-1}"

exec python scripts/run_smolvla_libero_closed_loop.py "$@"
