#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

exec uv run uvicorn xianglens.main:app \
  --host "${XIANG_HOST:-127.0.0.1}" \
  --port "${XIANG_PORT:-8080}"

