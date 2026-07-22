#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_file="${1:-$repo_root/models/gemma4-26b-q4/gemma-4-26B_q4_0-it.gguf}"
llama_server="${LLAMA_SERVER_BIN:-$repo_root/runtime/llama.cpp/build-rocm/bin/llama-server}"
expected_sha256="3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d"

if [[ ! -f "$model_file" ]]; then
  echo "Model file is unavailable: $model_file" >&2
  exit 1
fi
if [[ ! -x "$llama_server" ]]; then
  echo "llama-server is unavailable or not executable: $llama_server" >&2
  exit 1
fi
if [[ "${SIGNALFORGE_VERIFY_MODEL_HASH:-0}" == "1" ]]; then
  actual_sha256="$(sha256sum "$model_file" | awk '{print $1}')"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    echo "Model SHA-256 mismatch: $actual_sha256" >&2
    exit 1
  fi
fi

export HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-11.0.0}"
args=(
  --model "$model_file"
  --alias signalforge-gemma4-26b-q4
  --host "${SIGNALFORGE_MODEL_HOST:-127.0.0.1}"
  --port "${SIGNALFORGE_MODEL_PORT:-8000}"
  --ctx-size "${SIGNALFORGE_CONTEXT_SIZE:-32768}"
  --parallel "${SIGNALFORGE_PARALLEL_SLOTS:-4}"
  --batch-size "${SIGNALFORGE_BATCH_SIZE:-2048}"
  --ubatch-size "${SIGNALFORGE_UBATCH_SIZE:-512}"
  --flash-attn "${SIGNALFORGE_FLASH_ATTN:-auto}"
  --cache-type-k "${SIGNALFORGE_CACHE_TYPE_K:-f16}"
  --cache-type-v "${SIGNALFORGE_CACHE_TYPE_V:-f16}"
  --n-gpu-layers 999
  --jinja
  --metrics
  --no-webui
)

if [[ "${SIGNALFORGE_CONT_BATCHING:-1}" == "0" ]]; then
  args+=(--no-cont-batching)
else
  args+=(--cont-batching)
fi
if [[ "${SIGNALFORGE_KV_UNIFIED:-1}" == "0" ]]; then
  args+=(--no-kv-unified)
else
  args+=(--kv-unified)
fi

exec "$llama_server" "${args[@]}"
