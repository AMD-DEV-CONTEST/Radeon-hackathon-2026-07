#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVEROS_PREFIX="${EVEROS_PREFIX:-$PROJECT_ROOT/.runtime/everos}"
[[ -f "$PROJECT_ROOT/.env" ]] || { echo "Missing $PROJECT_ROOT/.env" >&2; exit 1; }

set -a
# shellcheck disable=SC1091
. "$PROJECT_ROOT/.env"
set +a

export EVEROS_ROOT="${EVEROS_ROOT:-${MEMORY_DATA_ROOT:-$PROJECT_ROOT/.runtime}/everos}"
export EVEROS_API__HOST="${EVEROS_API__HOST:-127.0.0.1}"
export EVEROS_API__PORT="${EVEROS_API__PORT:-8001}"
export EVEROS_LLM__MODEL="${EVEROS_LLM__MODEL:-qwen3.7-flash}"
export EVEROS_LLM__BASE_URL="${EVEROS_LLM__BASE_URL:-https://beaver-radeon-gateway.example/llm/v1}"
export EVEROS_LLM__API_KEY="${EVEROS_LLM__API_KEY:-}"
export EVEROS_MULTIMODAL__MODEL="${EVEROS_MULTIMODAL__MODEL:-qwen3.5-omni-flash}"
export EVEROS_MULTIMODAL__BASE_URL="${EVEROS_MULTIMODAL__BASE_URL:-https://beaver-radeon-gateway.example/llm/v1}"
export EVEROS_MULTIMODAL__API_KEY="${EVEROS_MULTIMODAL__API_KEY:-}"
export EVEROS_EMBEDDING__MODEL="qwen3-vl-embedding"
export EVEROS_EMBEDDING__API_KEY="${EVEROS_EMBEDDING__API_KEY:-}"
export EVEROS_EMBEDDING__BASE_URL="http://127.0.0.1:8792/v1"
export EVEROS_EMBEDDING__BATCH_SIZE="${EVEROS_EMBEDDING__BATCH_SIZE:-4}"
export EVEROS_EMBEDDING__MAX_CONCURRENT="${EVEROS_EMBEDDING__MAX_CONCURRENT:-1}"
export EVEROS_RERANK__PROVIDER="vllm"
export EVEROS_RERANK__MODEL="qwen3-vl-rerank"
export EVEROS_RERANK__API_KEY="${EVEROS_RERANK__API_KEY:-}"
export EVEROS_RERANK__BASE_URL="http://127.0.0.1:8792/v1"
export EVEROS_RERANK__BATCH_SIZE="${EVEROS_RERANK__BATCH_SIZE:-4}"
export EVEROS_RERANK__MAX_CONCURRENT="${EVEROS_RERANK__MAX_CONCURRENT:-1}"

exec "$EVEROS_PREFIX/.venv/bin/everos" server start
