#!/usr/bin/env bash
# Start the local LLM server for the diary app.
#
# Model: RobinsonLabs/Qwen3.6-35B-A3B-abliterated-GGUF (IQ4_XS, ~19 GB, cached).
# Runtime: llama.cpp (build at ~/envs/llama.cpp), offloads all layers to the AMD
#          GPU via ROCm (detects ROCm0 automatically; no Vulkan needed).
# API:     OpenAI-compatible, http://127.0.0.1:8089/v1
#
# Env overrides: DIARY_MODEL, LLAMA_BIN, DIARY_LLM_PORT, DIARY_LLM_CTX.
set -euo pipefail

MODEL="${DIARY_MODEL:-/home/pdfexe/.cache/huggingface/hub/models--RobinsonLabs--Qwen3.6-35B-A3B-abliterated-GGUF/snapshots/3f4e8b3793174de0243e2a5efb277223e97cb032/Qwen3.6-35B-A3B-abliterated-IQ4_XS.gguf}"
BIN="${LLAMA_BIN:-/home/pdfexe/envs/llama.cpp/llama.cpp/build/bin/llama-server}"
PORT="${DIARY_LLM_PORT:-8089}"
CONTEXT="${DIARY_LLM_CTX:-8192}"
# Optional vision projector for image-enrichment LLM-as-judge. Set to a mmproj
# .gguf path (or rely on the default below) to enable multimodal critique.
MMPROJ="${DIARY_MMPROJ:-/home/pdfexe/envs/llama.cpp/llama.cpp/models/qwen36-35b-a3b/mmproj-model-f16.gguf}"

if [ ! -f "$MODEL" ]; then
  echo "MODEL not found: $MODEL" >&2; exit 1
fi
if [ ! -x "$BIN" ]; then
  echo "llama-server not found/executable: $BIN" >&2; exit 1
fi

# Build the multimodal flag only if the projector file exists.
MMFLAGS=()
if [ -f "$MMPROJ" ]; then
  MMFLAGS=(--mmproj "$MMPROJ")
  echo "Vision enabled (mmproj): $MMPROJ"
else
  echo "No mmproj at $MMPROJ — starting text-only."
fi

echo "Starting llama-server on http://127.0.0.1:$PORT/v1 (ctx=$CONTEXT, all layers on GPU)"
nohup "$BIN" -m "$MODEL" --host 127.0.0.1 --port "$PORT" -c "$CONTEXT" -ngl 999 "${MMFLAGS[@]}" --verbose \
  > /tmp/llama_server.log 2>&1 &
echo "pid $! — log: /tmp/llama_server.log"
