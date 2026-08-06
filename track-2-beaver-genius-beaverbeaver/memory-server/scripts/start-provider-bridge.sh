#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -x "$PROJECT_ROOT/.venv/bin/uvicorn" ]] || {
  echo "Gateway environment is missing; run scripts/setup-gateway-linux.sh." >&2
  exit 1
}
exec "$PROJECT_ROOT/.venv/bin/uvicorn" \
  glass_gateway.provider_bridge:app \
  --app-dir "$PROJECT_ROOT/backend" \
  --host 127.0.0.1 \
  --port 8792
