#!/bin/bash
# Start the PrismML llama-server with the Ternary-Bonsai-27B GGUF.
set -e

LLAMA_PRISMML_DIR="${LLAMA_PRISMML_DIR:-/tmp/llama-prismml}"
MODEL_DIR="${MODEL_DIR:-$(dirname "$0")/../backend/models/chat}"
MODEL_FILE="$MODEL_DIR/Ternary-Bonsai-27B-Q2_0.gguf"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8082}"

if [ ! -f "$MODEL_FILE" ]; then
    echo "Model file not found: $MODEL_FILE"
    echo "Run scripts/setup_ternary_bonsai.sh first."
    exit 1
fi

if [ ! -x "$LLAMA_PRISMML_DIR/build/bin/llama-server" ]; then
    echo "llama-server binary not found: $LLAMA_PRISMML_DIR/build/bin/llama-server"
    echo "Run scripts/setup_ternary_bonsai.sh first."
    exit 1
fi

echo "Starting Ternary-Bonsai-27B chat server on $HOST:$PORT..."
exec "$LLAMA_PRISMML_DIR/build/bin/llama-server" \
  -m "$MODEL_FILE" \
  --host "$HOST" \
  --port "$PORT" \
  -ngl 999 \
  -c 2048 \
  --chat-template chatml
