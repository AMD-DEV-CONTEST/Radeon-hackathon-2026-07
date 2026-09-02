#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/server.sh
source "$ROOT_DIR/scripts/lib/server.sh"

SERVER_DRY_RUN=false
CONFIRMED=false
NO_START=false
BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) SERVER_DRY_RUN=true ;;
    --yes) CONFIRMED=true ;;
    --no-start) NO_START=true ;;
    --env) shift; [[ $# -gt 0 ]] || { echo "--env requires a path" >&2; exit 2; }; OPENALPHA_ENV_FILE="$1" ;;
    --file) shift; [[ $# -gt 0 ]] || { echo "--file requires a path" >&2; exit 2; }; BACKUP_FILE="$1" ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) [[ -z "$BACKUP_FILE" ]] || { echo "Only one backup file may be restored." >&2; exit 2; }; BACKUP_FILE="$1" ;;
  esac
  shift
done
export SERVER_DRY_RUN OPENALPHA_ENV_FILE
server_init "$ROOT_DIR"
openalpha_require_commands ssh rsync tar

[[ -n "$BACKUP_FILE" ]] || { echo "Usage: $0 --yes [--env FILE] BACKUP.tar.gz" >&2; exit 2; }
[[ -f "$BACKUP_FILE" ]] || { echo "Backup file not found: $BACKUP_FILE" >&2; exit 1; }
BACKUP_PERMISSIONS="$(stat -f '%Lp' "$BACKUP_FILE" 2>/dev/null || stat -c '%a' "$BACKUP_FILE" 2>/dev/null || true)"
BACKUP_PERMISSIONS="${BACKUP_PERMISSIONS: -3}"
if [[ "$BACKUP_PERMISSIONS" =~ ^[0-7]{3}$ ]] && (( (8#$BACKUP_PERMISSIONS & 077) != 0 )); then
  echo "Backup must not be group/world-readable: $BACKUP_FILE" >&2
  echo "Run: chmod 600 '$BACKUP_FILE'" >&2
  exit 1
fi
tar -tzf "$BACKUP_FILE" >/dev/null
if ! openalpha_is_true "$CONFIRMED" && ! openalpha_is_true "$SERVER_DRY_RUN"; then
  echo "Restore replaces remote state. Re-run with --yes after checking the backup." >&2
  exit 2
fi

REMOTE_ARCHIVE="/tmp/openalpha-restore-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
REMOTE_ROLLBACK_ARCHIVE="/tmp/openalpha-restore-rollback-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
REMOTE_ARCHIVE_READY=false
REMOTE_ROLLBACK_READY=false
STOP_ATTEMPTED=false
FAILURE_HANDLED=false
PROCESS_SCRIPT="$REMOTE_PROJECT_DIR/scripts/server_process.sh"
STATE_SCRIPT="$REMOTE_PROJECT_DIR/scripts/server_state.sh"
PREVIOUS_RUNNING_COMPONENTS=()
if openalpha_is_true "$SERVER_DRY_RUN"; then
  PREVIOUS_RUNNING_COMPONENTS=(llama api worker)
elif server_remote_capture test -x "$PROCESS_SCRIPT"; then
  for component in llama api worker; do
    if server_remote_capture "$PROCESS_SCRIPT" status "$component" >/dev/null 2>&1; then
      PREVIOUS_RUNNING_COMPONENTS+=("$component")
    fi
  done
fi

cleanup_remote_archive() {
  if openalpha_is_true "$STOP_ATTEMPTED" && ! openalpha_is_true "$FAILURE_HANDLED"; then
    echo "Restore exited unexpectedly; attempting automatic pre-restore recovery." >&2
    server_remote "$PROCESS_SCRIPT" stop all || true
    recovery_ok=true
    if openalpha_is_true "$REMOTE_ROLLBACK_READY"; then
      if ! server_remote "$STATE_SCRIPT" restore "$REMOTE_ROLLBACK_ARCHIVE" --yes; then
        recovery_ok=false
        REMOTE_ROLLBACK_READY=false
        echo "Automatic recovery failed; retained $REMOTE_ROLLBACK_ARCHIVE" >&2
      fi
    fi
    if openalpha_is_true "$recovery_ok"; then restart_previous_components || true; fi
  fi
  if openalpha_is_true "$REMOTE_ARCHIVE_READY"; then
    server_remote rm -f "$REMOTE_ARCHIVE" || true
  fi
  if openalpha_is_true "$REMOTE_ROLLBACK_READY"; then
    server_remote rm -f "$REMOTE_ROLLBACK_ARCHIVE" || true
  fi
}
trap cleanup_remote_archive EXIT

restart_previous_components() {
  local component
  if openalpha_is_true "$NO_START"; then return 0; fi
  for component in "${PREVIOUS_RUNNING_COMPONENTS[@]}"; do
    server_remote "$PROCESS_SCRIPT" start "$component" || return 1
  done
}

server_run_local rsync -az -e "$SERVER_RSYNC_SSH" \
  "$BACKUP_FILE" "$SERVER_TARGET:$REMOTE_ARCHIVE"
REMOTE_ARCHIVE_READY=true

# Validate both archive structure and member types before interrupting services.
server_remote "$STATE_SCRIPT" validate "$REMOTE_ARCHIVE"

STOP_ATTEMPTED=true
if server_remote "$PROCESS_SCRIPT" stop all; then
  :
else
  status=$?
  FAILURE_HANDLED=true
  restart_previous_components || true
  exit "$status"
fi

# Capture the exact pre-restore state while writers are stopped. It is used only
# if the restored deployment cannot pass startup health checks.
if server_remote bash -c '"$1" backup > "$2"' \
  openalpha-restore-rollback "$STATE_SCRIPT" "$REMOTE_ROLLBACK_ARCHIVE"; then
  if server_remote chmod 600 "$REMOTE_ROLLBACK_ARCHIVE" \
    && server_remote "$STATE_SCRIPT" validate "$REMOTE_ROLLBACK_ARCHIVE"; then
    REMOTE_ROLLBACK_READY=true
  else
    status=$?
    FAILURE_HANDLED=true
    restart_previous_components || true
    exit "$status"
  fi
else
  status=$?
  FAILURE_HANDLED=true
  restart_previous_components || true
  exit "$status"
fi

if server_remote "$STATE_SCRIPT" restore "$REMOTE_ARCHIVE" --yes; then
  :
else
  status=$?
  FAILURE_HANDLED=true
  echo "State restore failed; explicitly restoring the pre-restore snapshot." >&2
  server_remote "$PROCESS_SCRIPT" stop all || true
  if server_remote "$STATE_SCRIPT" restore "$REMOTE_ROLLBACK_ARCHIVE" --yes; then
    restart_previous_components || true
  else
    echo "Pre-restore state recovery failed; retained $REMOTE_ROLLBACK_ARCHIVE" >&2
    REMOTE_ROLLBACK_READY=false
  fi
  exit "$status"
fi
if ! openalpha_is_true "$NO_START"; then
  if server_remote "$PROCESS_SCRIPT" start all; then
    :
  else
    status=$?
    FAILURE_HANDLED=true
    echo "Restored services failed health checks; rolling back to pre-restore state." >&2
    server_remote "$PROCESS_SCRIPT" stop all || true
    if server_remote "$STATE_SCRIPT" restore "$REMOTE_ROLLBACK_ARCHIVE" --yes; then
      restart_previous_components || true
    else
      echo "Automatic state rollback failed; retained $REMOTE_ROLLBACK_ARCHIVE" >&2
      REMOTE_ROLLBACK_READY=false
    fi
    exit "$status"
  fi
fi
STOP_ATTEMPTED=false
echo "Restore completed from $BACKUP_FILE"
