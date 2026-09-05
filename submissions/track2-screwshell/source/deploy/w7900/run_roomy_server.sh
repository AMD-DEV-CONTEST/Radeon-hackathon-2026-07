#!/bin/bash
# ScrewShell roomy-mode llama-server for the W7900 (gfx1100) box.
#
# Preloads every available LoRA expert in ONE comma-separated --lora value.
# Repeated --lora flags are DEPRECATED in current llama.cpp: only the last one
# is honoured, which silently mounts a single adapter and degrades the rest to
# base. Keep the comma form.
#
# Adapter key == parent directory name of the .gguf. llama.cpp reports that name
# on /lora-adapters, and the router matches it against skill_map. So the layout
# must be loras/<logical_name>/adapter.gguf -- NOT loras/<name>/GGUF/foo.gguf,
# which would register the adapter as "GGUF" and silently never activate.
#
# Requires MOL_BACKEND=llamacpp on the UI side.
#
# NOTE: teichai_fable5_plan is intentionally absent -- no source weights exist
# for it anywhere (dl.sh fetches only 3; the skillpack ships a manifest only).
# The agent expert degrades to base until weights are supplied.

set -euo pipefail

ROOT=/workspace/persistent/screwshell_run
LLAMA=/opt/llama.cpp/build/bin/llama-server

cd "$ROOT"
export MOL_BACKEND=llamacpp

# P1 TTFT tuning (2026-08-05): flash-attn on + q8_0 KV cache quant + parallel 2.
# ctx-size kept at 8192 here (roomy/short-context mode); the production launcher
# (_llama_cmd_metrics.sh / run_gateway.sh) drops 131072 -> 98304.
exec "$LLAMA" \
  --model "$ROOT/models/Qwen3.6-27B-Q4_K_M.gguf" \
  --lora "$ROOT/loras/btl3/adapter.gguf,$ROOT/loras/cybersec/adapter.gguf,$ROOT/loras/rag_n7/adapter.gguf" \
  --alias m --host 127.0.0.1 --port 8080 \
  --ctx-size 8192 --n-gpu-layers 999 --threads 24 \
  --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 --parallel 2 \
  --metrics
