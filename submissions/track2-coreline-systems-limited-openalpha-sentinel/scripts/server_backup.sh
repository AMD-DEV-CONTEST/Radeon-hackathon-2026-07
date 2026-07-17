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
openalpha_require_commands ssh tar

: "${SERVER_BACKUP_DIR:=$ROOT_DIR/data/server-backups}"
if [[ "$SERVER_BACKUP_DIR" != /* ]]; then SERVER_BACKUP_DIR="$ROOT_DIR/$SERVER_BACKUP_DIR"; fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SAFE_HOST="${REMOTE_SSH_HOST//[^A-Za-z0-9._-]/_}"
BACKUP_FILE="$SERVER_BACKUP_DIR/openalpha-$SAFE_HOST-$STAMP.tar.gz"

if openalpha_is_true "$SERVER_DRY_RUN"; then
  server_print_command mkdir -p "$SERVER_BACKUP_DIR"
  server_print_command ssh "${SERVER_SSH_ARGS[@]}" "$SERVER_TARGET" \
    "$REMOTE_PROJECT_DIR/scripts/server_process.sh stop all"
  server_print_command ssh "${SERVER_SSH_ARGS[@]}" "$SERVER_TARGET" \
    "$REMOTE_PROJECT_DIR/scripts/server_state.sh backup" '>' "$BACKUP_FILE"
  server_print_command ssh "${SERVER_SSH_ARGS[@]}" "$SERVER_TARGET" \
    "$REMOTE_PROJECT_DIR/scripts/server_process.sh start all"
  exit 0
fi

umask 077
mkdir -p "$SERVER_BACKUP_DIR"
TEMP_FILE="${BACKUP_FILE}.partial"
REMOTE_PROCESS_SCRIPT="$REMOTE_PROJECT_DIR/scripts/server_process.sh"
RUNNING_COMPONENTS=()
STOP_ATTEMPTED=false
for component in llama api worker; do
  if server_remote_capture "$REMOTE_PROCESS_SCRIPT" status "$component" >/dev/null 2>&1; then
    RUNNING_COMPONENTS+=("$component")
  fi
done

cleanup_backup() {
  rm -f "$TEMP_FILE"
  if openalpha_is_true "$STOP_ATTEMPTED" && (( ${#RUNNING_COMPONENTS[@]} > 0 )); then
    echo "Backup did not finish cleanly; attempting to restart the previous services." >&2
    for component in "${RUNNING_COMPONENTS[@]}"; do
      server_remote "$REMOTE_PROCESS_SCRIPT" start "$component" || true
    done
  fi
}
trap cleanup_backup EXIT

# Freeze all writers so raw artifacts and the SQLite snapshot share one point in time.
STOP_ATTEMPTED=true
server_remote "$REMOTE_PROCESS_SCRIPT" stop all
server_remote_capture "$REMOTE_PROJECT_DIR/scripts/server_state.sh" backup > "$TEMP_FILE"
tar -tzf "$TEMP_FILE" >/dev/null
mv "$TEMP_FILE" "$BACKUP_FILE"
for component in "${RUNNING_COMPONENTS[@]}"; do
  server_remote "$REMOTE_PROCESS_SCRIPT" start "$component"
done
STOP_ATTEMPTED=false
trap - EXIT
echo "Backup saved to $BACKUP_FILE"
