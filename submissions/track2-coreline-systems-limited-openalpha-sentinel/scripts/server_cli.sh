#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/server.sh
source "$ROOT_DIR/scripts/lib/server.sh"

SERVER_DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) SERVER_DRY_RUN=true; shift ;;
    --env)
      shift
      [[ $# -gt 0 ]] || { echo "--env requires a path" >&2; exit 2; }
      OPENALPHA_ENV_FILE="$1"
      shift
      ;;
    --) shift; break ;;
    -*) echo "Unknown wrapper option: $1 (use -- before OpenAlpha options)" >&2; exit 2 ;;
    *) break ;;
  esac
done
[[ $# -gt 0 ]] || { echo "Usage: $0 [--env FILE] [--dry-run] [--] COMMAND [ARGS...]" >&2; exit 2; }

export SERVER_DRY_RUN OPENALPHA_ENV_FILE
server_init "$ROOT_DIR"
server_remote "$REMOTE_PROJECT_DIR/.venv/bin/openalpha" "$@"
