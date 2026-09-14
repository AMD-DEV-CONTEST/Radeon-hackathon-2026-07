#!/usr/bin/env bash
# Start the OpenAI-compatible SFT service (4-bit base + LoRA adapter).
# Portable launcher: set the three paths below, everything else is defaulted.
set -euo pipefail

# --- required ---
BASE_MODEL="${BASE_MODEL:?set BASE_MODEL to the local unsloth/Qwen3-32B-bnb-4bit snapshot dir}"
ADAPTER="${ADAPTER:?set ADAPTER to the checkpoint-000119 adapter dir (adapter_model.safetensors + adapter_config.json)}"
API_KEY_FILE="${API_KEY_FILE:?set API_KEY_FILE to a file containing one bearer token}"

# --- defaults ---
ALIAS="${ALIAS:-Qwen3-32B-Agentic-SFT-r1-v3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

exec python3 "$(dirname "$0")/qwen3_agentic_openai_server.py" \
  --model "$BASE_MODEL" \
  --adapter "$ADAPTER" \
  --alias "$ALIAS" \
  --api-key-file "$API_KEY_FILE" \
  --host "$HOST" --port "$PORT"
