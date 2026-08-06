#!/usr/bin/env bash
set -euo pipefail

SERVER=/persistent/yijian/llama.cpp/build/bin/llama-server
BASE=/persistent/yijian/models/qwen3-14b-lora-preview/qwen3-14b-q4_k_m.gguf
RELEASE=/persistent/yijian/models/yijian-lora-v3-frozen
ADAPTER="$RELEASE/yijian-lora-v3-f16.gguf"
LOG=/persistent/yijian/logs/qwen3-14b-lora-v3-server.log
PORT="${YIJIAN_LORA_PREVIEW_PORT:-8083}"

test -x "$SERVER"
test -f "$BASE"
test -f "$ADAPTER"
(cd "$RELEASE" && sha256sum -c GGUF-SHA256SUMS)

pkill -f "llama-server.*--port $PORT" || true
pkill -f '[s]erve_lora_transformers.py' || true
for _ in $(seq 1 60); do
  pgrep -f "llama-server.*--port $PORT" >/dev/null || break
  sleep 1
done

nohup "$SERVER" \
  --model "$BASE" \
  --lora "$ADAPTER" \
  --alias YIJIAN-Qwen3-14B-LoRA-gold-runtime-v3-Q4 \
  --host 127.0.0.1 --port "$PORT" \
  --ctx-size 8192 --parallel 1 --n-gpu-layers 99 \
  --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 \
  --cache-reuse 256 --no-ui \
  >>"$LOG" 2>&1 &

for _ in $(seq 1 180); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null; then
    curl -fsS "http://127.0.0.1:$PORT/v1/models"
    exit 0
  fi
  sleep 1
done

echo "YIJIAN LoRA v3 fast preview failed to become healthy" >&2
exit 1
