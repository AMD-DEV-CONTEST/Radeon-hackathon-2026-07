#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/server.sh
source "$ROOT_DIR/scripts/lib/server.sh"

SERVER_DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) SERVER_DRY_RUN=true ;;
    --env) shift; [[ $# -gt 0 ]] || { echo "--env requires a path" >&2; exit 2; }; OPENALPHA_ENV_FILE="$1" ;;
    *) echo "Usage: $0 [--env FILE] [--dry-run]" >&2; exit 2 ;;
  esac
  shift
done
export SERVER_DRY_RUN OPENALPHA_ENV_FILE
server_init "$ROOT_DIR"

: "${LOCAL_TUNNEL_PORT:=8765}"
: "${OPENALPHA_PORT:=8765}"
server_validate_port LOCAL_TUNNEL_PORT "$LOCAL_TUNNEL_PORT"
server_validate_port OPENALPHA_PORT "$OPENALPHA_PORT"

TUNNEL_COMMAND=(
  ssh "${SERVER_SSH_ARGS[@]}"
  -o ExitOnForwardFailure=yes
  -N -L "127.0.0.1:${LOCAL_TUNNEL_PORT}:127.0.0.1:${OPENALPHA_PORT}"
  "$SERVER_TARGET"
)
echo "Open http://127.0.0.1:${LOCAL_TUNNEL_PORT} while this tunnel is running."
server_print_command "${TUNNEL_COMMAND[@]}"
if ! openalpha_is_true "$SERVER_DRY_RUN"; then
  exec "${TUNNEL_COMMAND[@]}"
fi
