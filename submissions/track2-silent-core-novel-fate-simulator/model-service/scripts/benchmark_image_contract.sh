#!/usr/bin/env bash
set -euo pipefail

ROOT=/persistent/silent-core
set -a
source "$ROOT/config.env"
set +a

OUTPUT_PREFIX="${1:-image-contract}"
MODEL_BASE_URL="${MODEL_BASE_URL:-http://127.0.0.1:18000}"
rm -f "$ROOT/run/$OUTPUT_PREFIX.done"

started=$(date +%s.%N)
status=$(curl -sS --max-time 300 \
  -o "$ROOT/logs/$OUTPUT_PREFIX.json" \
  -w "%{http_code}" \
  "$MODEL_BASE_URL/v1/images/generations" \
  -H "Authorization: Bearer $SILENT_CORE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"silent-core/image","prompt":"A cinematic moonlit fantasy library, English visual novel background, detailed lighting","size":"1024x1536","n":1,"response_format":"url","seed":2026}')
finished=$(date +%s.%N)

python3 - "$status" "$started" "$finished" > "$ROOT/logs/$OUTPUT_PREFIX.meta" <<'PY'
import sys

status, started, finished = sys.argv[1:]
print(f"status={status} elapsed={float(finished) - float(started):.3f}")
PY
touch "$ROOT/run/$OUTPUT_PREFIX.done"
