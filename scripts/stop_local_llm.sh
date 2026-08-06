#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
source "$SCRIPT_DIR/process_helpers.sh"
bg_stop_pid "$BG_RUN/llama-server.pid" "llama-server" 30
echo "llama-server stopped"
