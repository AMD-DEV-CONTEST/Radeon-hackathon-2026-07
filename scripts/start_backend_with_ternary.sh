#!/bin/bash
# Start the FastAPI backend using the external Ternary-Bonsai-27B chat server.
set -e

PORT="${PORT:-8000}"
CHAT_HOST="${CHAT_HOST:-127.0.0.1}"
CHAT_PORT="${CHAT_PORT:-8082}"

export CHAT_OPENAI_BASE_URL="http://$CHAT_HOST:$CHAT_PORT/v1"
export CHAT_OPENAI_MODEL="${CHAT_OPENAI_MODEL:-Ternary-Bonsai-27B-Q2_0.gguf}"

echo "Starting backend on port $PORT, chat server at $CHAT_OPENAI_BASE_URL..."

cd "$(dirname "$0")/../backend"
conda run -n e2e python -m uvicorn main:app --host 0.0.0.0 --port "$PORT"
