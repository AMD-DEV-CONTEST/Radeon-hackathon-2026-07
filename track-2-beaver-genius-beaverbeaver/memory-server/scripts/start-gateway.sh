#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  echo "Missing $PROJECT_ROOT/.env; copy .env.example and configure it first." >&2
  exit 1
fi
if [[ ! -x "$PROJECT_ROOT/.venv/bin/uvicorn" ]]; then
  echo "Gateway environment is missing; run scripts/setup-gateway-linux.sh." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. "$PROJECT_ROOT/.env"
set +a

exec "$PROJECT_ROOT/.venv/bin/uvicorn" \
  glass_gateway.app:app \
  --app-dir "$PROJECT_ROOT/backend" \
  --host "${BACKEND_HOST:-${GLASS_BACKEND_HOST:-0.0.0.0}}" \
  --port "${BACKEND_PORT:-${GLASS_BACKEND_PORT:-8788}}"
