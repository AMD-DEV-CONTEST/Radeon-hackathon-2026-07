#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

api_host="${API_HOST:-127.0.0.1}"
api_port="${API_PORT:-8080}"

case "$api_host" in
  127.0.0.1|localhost|::1) ;;
  *)
    echo "ERROR: Case API may only listen on a loopback address." >&2
    exit 2
    ;;
esac

if ! [[ "$api_port" =~ ^[0-9]+$ ]] || (( api_port < 1 || api_port > 65535 )); then
  echo "ERROR: API_PORT must be an integer from 1 to 65535." >&2
  exit 2
fi

PERSISTENT_PYTHON_PACKAGES="${PERSISTENT_PYTHON_PACKAGES:-/persistent/python-packages}"
export PYTHONPATH="$PERSISTENT_PYTHON_PACKAGES${PYTHONPATH:+:$PYTHONPATH}"
exec /opt/venv/bin/python -m uvicorn app.api.main:app \
  --host "$api_host" \
  --port "$api_port"
