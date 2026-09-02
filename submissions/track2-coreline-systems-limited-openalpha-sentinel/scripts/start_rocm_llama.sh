#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"
openalpha_load_env "$ROOT_DIR" runtime optional

MODEL_PATH="${MODEL_PATH:-}"
LLAMA_SOURCE="${LLAMA_SOURCE:-$ROOT_DIR/vendor/llama.cpp}"
LLAMA_BUILD="${LLAMA_BUILD:-$LLAMA_SOURCE/build}"
LLAMA_BIN="${LLAMA_BIN:-$LLAMA_BUILD/bin/llama-server}"
LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLAMA_CTX="${LLAMA_CTX:-8192}"
LLAMA_GPU_LAYERS="${LLAMA_GPU_LAYERS:-99}"
LLAMA_LOG_VERBOSITY="${LLAMA_LOG_VERBOSITY:-4}"

if [[ -z "$MODEL_PATH" || ! -f "$MODEL_PATH" ]]; then
  echo "Set MODEL_PATH to the verified GGUF model file." >&2
  exit 1
fi
if [[ ! -x "$LLAMA_BIN" ]]; then
  echo "llama-server is missing at $LLAMA_BIN" >&2
  exit 1
fi
if [[ ! "$LLAMA_LOG_VERBOSITY" =~ ^[0-9]+$ ]]; then
  echo "LLAMA_LOG_VERBOSITY must be a non-negative integer." >&2
  exit 1
fi

if [[ -n "${MODEL_SHA256:-}" ]]; then
  openalpha_require_commands sha256sum
  if ! echo "$MODEL_SHA256  $MODEL_PATH" | sha256sum --check --status; then
    echo "MODEL_SHA256 does not match $MODEL_PATH" >&2
    exit 1
  fi
fi

exec "$LLAMA_BIN" \
  --model "$MODEL_PATH" \
  --host "$LLAMA_HOST" \
  --port "$LLAMA_PORT" \
  --ctx-size "$LLAMA_CTX" \
  --n-gpu-layers "$LLAMA_GPU_LAYERS" \
  --verbosity "$LLAMA_LOG_VERBOSITY" \
  --flash-attn on \
  --metrics
