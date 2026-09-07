#!/usr/bin/env bash
set -euo pipefail

set -a
source /persistent/silent-core/config.env
set +a
exec /opt/venv/bin/uvicorn gateway:app \
  --app-dir /persistent/silent-core/src \
  --host 127.0.0.1 \
  --port 18000
