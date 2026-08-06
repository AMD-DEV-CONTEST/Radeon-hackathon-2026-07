#!/bin/bash
# smoke_local.sh — one-command local smoke (Todo 11): API up + health + key endpoints.
# Exits 0 when the local stack answers; nonzero otherwise (also used by the
# stopped-endpoint failure case which expects nonzero).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="${LC_API_URL:-http://127.0.0.1:8510}"
PY="${LC_PYTHON:-/opt/venv/bin/python}"

# health endpoint (or stats fallback)
if ! curl -fsS --max-time 5 "$API/health" >/dev/null 2>&1; then
  if ! curl -fsS --max-time 5 "$API/api/stats" >/dev/null 2>&1; then
    echo "SMOKE_FAIL: API $API not answering" >&2
    exit 1
  fi
fi

# key endpoints answer with 200
for path in /api/stats /api/garden; do
  code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$API$path" 2>/dev/null)"
  if [ "$code" != "200" ]; then
    echo "SMOKE_FAIL: $API$path -> $code" >&2
    exit 1
  fi
done

# web dist built (SPA fallback serves index.html)
code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$API/garden" 2>/dev/null)"
if [ "$code" != "200" ]; then
  echo "SMOKE_FAIL: SPA fallback /garden -> $code" >&2
  exit 1
fi

echo "SMOKE_OK: API healthy; stats/garden/SPA-fallback 200"
exit 0
