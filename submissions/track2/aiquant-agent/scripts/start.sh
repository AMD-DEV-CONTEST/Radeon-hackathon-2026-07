#!/bin/bash
# aiQuant Start Script — for Radeon Cloud (AMD GPU)
# Usage: bash scripts/start.sh
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT/src"

# Load .env if exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Defaults (overridable by .env)
export LLM_API_BASE=${LLM_API_BASE:-http://localhost:13305/v1}
export LLM_API_KEY=${LLM_API_KEY:-lemonade}
export LLM_MODEL=${LLM_MODEL:-/root/.cache/lemonade/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf}
export OPENAI_API_BASE=${OPENAI_API_BASE:-$LLM_API_BASE}
export OPENAI_API_KEY=${OPENAI_API_KEY:-$LLM_API_KEY}
export CHAT_MODEL=${CHAT_MODEL:-$LLM_MODEL}
export CHAT_TOKEN_LIMIT=${CHAT_TOKEN_LIMIT:-32768}
export RUN_MODE=${RUN_MODE:-local}
export CONDA_DEFAULT_ENV=${CONDA_DEFAULT_ENV:-base}

echo "=== aiQuant Starting ==="
echo "LLM API:  $LLM_API_BASE"
echo "Model:    $LLM_MODEL"
echo "Port:     8010"
echo "Mode:     $RUN_MODE"
echo ""

# Install dependencies if needed
pip install -q -r requirements.txt 2>/dev/null || true

# Start API server
exec uvicorn backend.api.main:app \
    --host 0.0.0.0 \
    --port 8010 \
    --loop asyncio \
    --log-level info
