#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
  chmod 600 "$PROJECT_ROOT/.env"
  echo "Created $PROJECT_ROOT/.env; configure external services before starting."
fi
set -a
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.env"
set +a
MEMORY_DATA_ROOT="${MEMORY_DATA_ROOT:-$PROJECT_ROOT/.runtime}"

command -v uv >/dev/null 2>&1 || {
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
}
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "Python 3.12 is required (set PYTHON_BIN to its executable)." >&2
  exit 1
}

"$PYTHON_BIN" -c '
import sys
if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"Python 3.12 required, found {sys.version.split()[0]}")
'

uv venv --python "$PYTHON_BIN" "$PROJECT_ROOT/.venv"
uv pip install \
  --python "$PROJECT_ROOT/.venv/bin/python" \
  -r "$PROJECT_ROOT/backend/requirements.txt" \
  -r "$PROJECT_ROOT/backend/requirements-presence.txt"

mkdir -p \
  "$MEMORY_DATA_ROOT/raw-media" \
  "$MEMORY_DATA_ROOT/received-photos" \
  "$MEMORY_DATA_ROOT/users" \
  "$MEMORY_DATA_ROOT/identity/protected" \
  "$MEMORY_DATA_ROOT/voice/protected" \
  "$PROJECT_ROOT/.runtime/logs" \
  "$PROJECT_ROOT/.runtime/pids"

echo "Gateway environment ready: $PROJECT_ROOT/.venv"
