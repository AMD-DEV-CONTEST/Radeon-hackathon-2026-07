#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
for url in \
  http://127.0.0.1:8080/v1/models \
  http://127.0.0.1:8000/health \
  http://127.0.0.1:8501/_stcore/health \
  http://127.0.0.1:8501/; do
  curl --fail --show-error --silent --max-time 30 "$url" >/dev/null
  echo "OK $url"
done
curl --fail --show-error --silent --max-time 30 \
  http://127.0.0.1:8000/openapi.json \
  | "$BG_VENV/bin/python" -c '
import json
import sys

paths = json.load(sys.stdin).get("paths", {})
required = {"/agent/chat", "/agent/chat/stream", "/agent/confirm"}
missing = sorted(required - set(paths))
if missing:
    raise SystemExit(f"Missing Chat-first API routes: {missing}")
'
echo "OK Chat-first API contract"
ss -lntp | grep -E ':(8000|8080|8501)\b'
