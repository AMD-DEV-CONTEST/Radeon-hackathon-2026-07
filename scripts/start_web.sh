#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir/apps/web"

exec pnpm run dev --host "${XIANG_WEB_HOST:-127.0.0.1}" --port "${XIANG_WEB_PORT:-3000}"
