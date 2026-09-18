#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
source "$SCRIPT_DIR/process_helpers.sh"
[[ -x "$BG_VENV/bin/buildguard" ]] || { echo "Missing environment: $BG_VENV" >&2; exit 1; }
bg_require_free_port 8000
cd "$BG_REPO"
nohup "$BG_VENV/bin/buildguard" serve-api --config "$BG_CONFIG" \
  >"$BG_LOGS/buildguard-api.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$BG_RUN/buildguard-api.pid"
echo "BuildGuard API PID=$pid"
