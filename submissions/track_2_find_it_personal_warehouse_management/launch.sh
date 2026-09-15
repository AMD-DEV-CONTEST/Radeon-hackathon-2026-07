#!/usr/bin/env bash
# launch.sh — start the Find it FastAPI daemon.
#
# Env overrides:  VENV_DIR, HOST, PORT
ps aux | grep 8090 | grep python | awk '{print $2}' | xargs -Iabc kill abc

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR=".venv"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8090}"

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"


cd "$HERE"
echo "==> Serving on http://${HOST}:${PORT}  (open http://localhost:${PORT})"
exec uvicorn main:app --host "$HOST" --port "$PORT" "$@"
