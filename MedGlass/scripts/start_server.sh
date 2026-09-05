#!/bin/bash
# Start the MedGlass server fully detached.
# Usage: bash scripts/start_server.sh [--host 0.0.0.0] [--port 8100]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HOST="${1:-127.0.0.1}"
PORT="${2:-8100}"

LOG="$ROOT/output/server.log"
mkdir -p "$ROOT/output"

# Source project .env if present (API keys, tokens)
if [ -f "$ROOT/.env" ]; then
  set -a; source "$ROOT/.env"; set +a
fi

# Optional server-side env (e.g. MEDGLASS_DASHBOARD_TOKEN) from output/server.env
if [ -f "$ROOT/output/server.env" ]; then
  set -a; source "$ROOT/output/server.env"; set +a
fi

# Prefer the project venv (created by setup.sh) when present, else system python.
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

nohup "$PY" -m uvicorn server:app \
  --host "$HOST" --port "$PORT" --log-level warning \
  --app-dir "$ROOT/src" \
  > "$LOG" 2>&1 &

echo "MedGlass server starting at http://$HOST:$PORT  (log: $LOG)"
echo "PID: $!"
