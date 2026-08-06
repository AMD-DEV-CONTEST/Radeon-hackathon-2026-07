#!/usr/bin/env bash
# Example: serve BAAI/bge-small-zh-v1.5 for PrivatePlate local RAG on loopback :8001.
# Chat model (Gemma etc.) stays on :8000. Adjust flags for your ROCm vLLM build.
set -euo pipefail

MODEL="${PRIVATEPLATE_EMBEDDING_MODEL:-BAAI/bge-small-zh-v1.5}"
HOST="${PRIVATEPLATE_EMBEDDING_HOST:-127.0.0.1}"
PORT="${PRIVATEPLATE_EMBEDDING_PORT:-8001}"

echo "[serve-bge] model=${MODEL} ${HOST}:${PORT}"
echo "[serve-bge] After ready, run: npm run rag:check"

# Prefer modern task flag; fall back to plain serve if your build rejects --task.
if vllm serve --help 2>/dev/null | grep -q -- '--task'; then
  exec vllm serve "${MODEL}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --task embed
else
  exec vllm serve "${MODEL}" \
    --host "${HOST}" \
    --port "${PORT}"
fi
