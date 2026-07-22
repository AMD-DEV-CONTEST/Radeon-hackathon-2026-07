#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/server.sh
source "$ROOT_DIR/scripts/lib/server.sh"

SERVER_DRY_RUN=false
COMPONENT=""
LINES=100
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) SERVER_DRY_RUN=true ;;
    --env) shift; [[ $# -gt 0 ]] || { echo "--env requires a path" >&2; exit 2; }; OPENALPHA_ENV_FILE="$1" ;;
    --lines) shift; [[ $# -gt 0 ]] || { echo "--lines requires a number" >&2; exit 2; }; LINES="$1" ;;
    llama|api|worker) [[ -z "$COMPONENT" ]] || { echo "Choose one component." >&2; exit 2; }; COMPONENT="$1" ;;
    *) echo "Usage: $0 [--env FILE] [--lines N] [--dry-run] llama|api|worker" >&2; exit 2 ;;
  esac
  shift
done

[[ -n "$COMPONENT" ]] || { echo "Choose llama, api, or worker." >&2; exit 2; }
[[ "$LINES" =~ ^[1-9][0-9]*$ ]] || { echo "--lines must be a positive integer." >&2; exit 2; }

export SERVER_DRY_RUN OPENALPHA_ENV_FILE
server_init "$ROOT_DIR"
: "${OPENALPHA_LOG_DIR:?OPENALPHA_LOG_DIR is required}"
server_validate_remote_path OPENALPHA_LOG_DIR "$OPENALPHA_LOG_DIR"
server_remote tail -n "$LINES" "$OPENALPHA_LOG_DIR/$COMPONENT.log"
