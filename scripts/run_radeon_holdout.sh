#!/usr/bin/env bash
set -euo pipefail

ROOT="${CLAIMCOURT_ROOT:-/workspace/claimcourt}"
PYTHON="${CLAIMCOURT_PYTHON:-/opt/venv/bin/python}"
ROUTER_ENDPOINT="${CLAIMCOURT_ROUTER_ENDPOINT:-http://127.0.0.1:8000/v1}"
ROUTER_MODEL="${CLAIMCOURT_ROUTER_MODEL:-claimcourt-intent}"
EMBEDDING_ENDPOINT="${CLAIMCOURT_EMBEDDING_ENDPOINT:-http://127.0.0.1:8001/v1}"
EMBEDDING_MODEL="${CLAIMCOURT_EMBEDDING_MODEL:-/workspace/models/bge-small-zh-v1.5}"
RERANKER_MODEL="${CLAIMCOURT_RERANKER_MODEL:-}"
RERANKER_DEVICE="${CLAIMCOURT_RERANKER_DEVICE:-cuda}"
ROUTER_CONCURRENCY="${CLAIMCOURT_ROUTER_CONCURRENCY:-8}"
OUTPUT="${CLAIMCOURT_HOLDOUT_OUTPUT:-/workspace/logs/fuzzy-holdout-live.json}"

if [[ -z "$RERANKER_MODEL" ]]; then
  echo "CLAIMCOURT_RERANKER_MODEL must point to a local cross-encoder checkpoint" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUTPUT")"
cd "$ROOT"

"$PYTHON" scripts/adversarial_holdout_check.py \
  --root evaluation/fuzzy_holdout_v1 \
  --output "$OUTPUT" \
  --router-runtime vllm \
  --router-endpoint "$ROUTER_ENDPOINT" \
  --router-model "$ROUTER_MODEL" \
  --embedding-runtime vllm \
  --embedding-endpoint "$EMBEDDING_ENDPOINT" \
  --embedding-model "$EMBEDDING_MODEL" \
  --reranker-model "$RERANKER_MODEL" \
  --reranker-device "$RERANKER_DEVICE" \
  --router-concurrency "$ROUTER_CONCURRENCY" \
  --require-live-stack

echo "Live Radeon holdout passed: $OUTPUT"
