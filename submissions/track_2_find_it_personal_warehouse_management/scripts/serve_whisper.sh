#!/usr/bin/env bash
# serve_whisper.sh — start the whisper.cpp ASR server.
#
# Assumes setup_whisper.sh has already been run. The server listens on
# 127.0.0.1:8080 (the default expected by the web app). Adjust ASR_API_URL
# in .env if you run it elsewhere.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$HERE/.."
WHISPER_DIR="$ROOT/models/whisper/whisper-v1.8.4-linux-vulkan-x86_64"
MODEL="$ROOT/models/whisper/ggml-large-v3-turbo-q5_0.bin"

if [ ! -d "$WHISPER_DIR" ]; then
  echo "ERROR: whisper.cpp directory not found at $WHISPER_DIR"
  echo "Run ./scripts/setup_whisper.sh first."
  exit 1
fi
if [ ! -f "$MODEL" ]; then
  echo "ERROR: model not found at $MODEL"
  echo "Run ./scripts/setup_whisper.sh first."
  exit 1
fi

cd "$WHISPER_DIR"
echo "==> Starting whisper-server on http://127.0.0.1:8080"
exec ./whisper-server -m "$MODEL" --host 127.0.0.1 --port 8080 "$@"
