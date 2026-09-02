#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/server.sh
source "$ROOT_DIR/scripts/lib/server.sh"

SERVER_DRY_RUN=false
NO_START=false
PREPARE_LLAMA=true
SKIP_LLAMA_BUILD=false
BOOTSTRAP_ARGS=()
SYNC_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) SERVER_DRY_RUN=true ;;
    --no-start) NO_START=true ;;
    --skip-llama-prepare) PREPARE_LLAMA=false ;;
    --skip-llama-build) SKIP_LLAMA_BUILD=true; BOOTSTRAP_ARGS+=("$1") ;;
    --skip-packages|--skip-systemd) BOOTSTRAP_ARGS+=("$1") ;;
    --with-model|--without-model|--with-llama-source|--without-llama-source) SYNC_ARGS+=("$1") ;;
    --env)
      shift
      [[ $# -gt 0 ]] || { echo "--env requires a path" >&2; exit 2; }
      OPENALPHA_ENV_FILE="$1"
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
export SERVER_DRY_RUN OPENALPHA_ENV_FILE

server_init "$ROOT_DIR"
: "${MODEL_PATH:=}"
MODEL_PREVIOUS=""
MODEL_FAILED=""
MODEL_TRANSACTION_ARMED=false
if [[ -n "$MODEL_PATH" ]]; then
  server_validate_remote_path MODEL_PATH "$MODEL_PATH"
  MODEL_PREVIOUS="${MODEL_PATH}.pre-deploy"
  MODEL_FAILED="${MODEL_PATH}.failed-deploy-$$"
fi

DEPLOY_SUCCEEDED=false
PREVIOUS_RUNNING_COMPONENTS=()
PREVIOUS_ENABLED_UNITS=()
SYSTEMD_WAS_ONLINE=false
REMOTE_PROCESS_SCRIPT="$REMOTE_PROJECT_DIR/scripts/server_process.sh"
REMOTE_ROLLBACK_DIR="${REMOTE_PROJECT_DIR}.rollback-$$"
ROLLBACK_READY=false
ENV_BACKUP_READY=false
DEPLOY_STOP_ATTEMPTED=false
if ! openalpha_is_true "$SERVER_DRY_RUN" \
  && server_remote_capture test -x "$REMOTE_PROCESS_SCRIPT"; then
  for component in llama api worker; do
    if server_remote_capture "$REMOTE_PROCESS_SCRIPT" status "$component" >/dev/null 2>&1; then
      PREVIOUS_RUNNING_COMPONENTS+=("$component")
    fi
  done
fi
if ! openalpha_is_true "$SERVER_DRY_RUN" \
  && server_remote_capture test -d /run/systemd/system \
  && server_remote_capture systemctl show-environment >/dev/null 2>&1; then
  SYSTEMD_WAS_ONLINE=true
  for unit in openalpha-llama.service openalpha-api.service openalpha-worker.service; do
    if server_remote_capture systemctl is-enabled --quiet "$unit"; then
      PREVIOUS_ENABLED_UNITS+=("$unit")
    fi
  done
fi

recover_previous_deployment() {
  if ! openalpha_is_true "$DEPLOY_SUCCEEDED"; then
    local recovery_ok=true
    if openalpha_is_true "$DEPLOY_STOP_ATTEMPTED"; then
      server_remote bash -c \
        'if [[ -x "$1" ]]; then "$1" stop all; fi' \
        openalpha-recovery-stop "$REMOTE_PROCESS_SCRIPT" || true
    fi
    if openalpha_is_true "$ROLLBACK_READY"; then
      if server_remote rsync -a --delete --exclude='.env*' \
        "$REMOTE_ROLLBACK_DIR/" "$REMOTE_PROJECT_DIR/"; then
        server_remote rm -rf "$REMOTE_ROLLBACK_DIR" || true
        ROLLBACK_READY=false
      else
        echo "Remote code rollback failed; retained snapshot: $REMOTE_ROLLBACK_DIR" >&2
        recovery_ok=false
      fi
    fi
    if openalpha_is_true "$ENV_BACKUP_READY"; then
      if ! server_remote bash -c \
        'if [[ -f "$1/.env.pre-deploy" ]]; then mv -f "$1/.env.pre-deploy" "$1/.env"; chmod 600 "$1/.env"; fi' \
        openalpha-env-restore "$REMOTE_PROJECT_DIR"; then
        echo "Remote environment rollback failed." >&2
        recovery_ok=false
      fi
    fi
    if openalpha_is_true "$MODEL_TRANSACTION_ARMED" \
      && server_remote_capture test -e "$MODEL_PREVIOUS"; then
      if server_remote_capture test -e "$MODEL_FAILED"; then
        echo "Model rollback collision: $MODEL_FAILED" >&2
        recovery_ok=false
      elif server_remote_capture test -e "$MODEL_PATH" \
        && ! server_remote mv "$MODEL_PATH" "$MODEL_FAILED"; then
        echo "Could not isolate the failed deployment model." >&2
        recovery_ok=false
      elif server_remote mv "$MODEL_PREVIOUS" "$MODEL_PATH"; then
        server_remote rm -f "$MODEL_FAILED" || true
      else
        echo "Could not restore the previous deployment model." >&2
        if server_remote_capture test -e "$MODEL_FAILED" \
          && ! server_remote_capture test -e "$MODEL_PATH"; then
          server_remote mv "$MODEL_FAILED" "$MODEL_PATH" || true
        fi
        recovery_ok=false
      fi
    fi
    if openalpha_is_true "$SYSTEMD_WAS_ONLINE"; then
      if ! server_remote systemctl disable openalpha-llama.service openalpha-api.service \
        openalpha-worker.service; then
        recovery_ok=false
      fi
      if (( ${#PREVIOUS_ENABLED_UNITS[@]} > 0 )) \
        && ! server_remote systemctl enable "${PREVIOUS_ENABLED_UNITS[@]}"; then
        recovery_ok=false
      fi
    fi
    if (( ${#PREVIOUS_RUNNING_COMPONENTS[@]} > 0 )) && ! openalpha_is_true "$NO_START"; then
      if openalpha_is_true "$recovery_ok"; then
        echo "Deployment failed; attempting to restart the previous remote services." >&2
        for component in "${PREVIOUS_RUNNING_COMPONENTS[@]}"; do
          server_remote "$REMOTE_PROCESS_SCRIPT" start "$component" || true
        done
      else
        echo "Rollback was incomplete; services remain stopped for manual recovery." >&2
      fi
    fi
  fi
}
trap recover_previous_deployment EXIT

if openalpha_is_true "$PREPARE_LLAMA" && ! openalpha_is_true "$SKIP_LLAMA_BUILD"; then
  PREPARE_COMMAND=("$ROOT_DIR/scripts/prepare_llama_source.sh" --env "$OPENALPHA_LOADED_ENV_FILE")
  if openalpha_is_true "$SERVER_DRY_RUN"; then PREPARE_COMMAND+=(--dry-run); fi
  "${PREPARE_COMMAND[@]}"
fi

# Stop an existing deployment before replacing code or its virtual environment.
# The conditional also keeps first-time deployment idempotent.
if ! openalpha_is_true "$SERVER_DRY_RUN" && server_remote_capture test -L "$REMOTE_PROJECT_DIR"; then
  echo "Refusing to deploy through a symlinked REMOTE_PROJECT_DIR: $REMOTE_PROJECT_DIR" >&2
  exit 1
fi
if ! openalpha_is_true "$SERVER_DRY_RUN" && [[ -n "$MODEL_PREVIOUS" ]] \
  && server_remote_capture test -e "$MODEL_PREVIOUS"; then
  echo "Unresolved model rollback file exists: $MODEL_PREVIOUS" >&2
  exit 1
fi
if ! openalpha_is_true "$SERVER_DRY_RUN" && [[ -n "$MODEL_PREVIOUS" ]]; then
  MODEL_TRANSACTION_ARMED=true
fi
if ! openalpha_is_true "$SERVER_DRY_RUN" && server_remote_capture test -d "$REMOTE_PROJECT_DIR"; then
  server_remote mkdir -p "$REMOTE_ROLLBACK_DIR"
  server_remote rsync -a --delete --exclude='.env*' \
    "$REMOTE_PROJECT_DIR/" "$REMOTE_ROLLBACK_DIR/"
  ROLLBACK_READY=true
fi
if openalpha_is_true "$SERVER_DRY_RUN"; then
  server_remote bash -c \
    'if [[ -f "$1/.env" ]]; then cp -p "$1/.env" "$1/.env.pre-deploy"; chmod 600 "$1/.env.pre-deploy"; fi' \
    openalpha-env-backup "$REMOTE_PROJECT_DIR"
elif server_remote_capture test -f "$REMOTE_PROJECT_DIR/.env"; then
  server_remote cp -p "$REMOTE_PROJECT_DIR/.env" "$REMOTE_PROJECT_DIR/.env.pre-deploy"
  server_remote chmod 600 "$REMOTE_PROJECT_DIR/.env.pre-deploy"
  ENV_BACKUP_READY=true
fi
DEPLOY_STOP_ATTEMPTED=true
server_remote bash -c \
  'if [[ -x "$1" ]]; then "$1" stop all; fi' \
  openalpha-deploy "$REMOTE_PROCESS_SCRIPT"

SYNC_COMMAND=("$ROOT_DIR/scripts/server_sync.sh" --env "$OPENALPHA_LOADED_ENV_FILE")
if (( ${#SYNC_ARGS[@]} > 0 )); then SYNC_COMMAND+=("${SYNC_ARGS[@]}"); fi
if openalpha_is_true "$SERVER_DRY_RUN"; then SYNC_COMMAND+=(--dry-run); fi
"${SYNC_COMMAND[@]}"

if openalpha_is_true "$SERVER_DRY_RUN"; then
  BOOTSTRAP_ARGS+=(--dry-run)
fi
if (( ${#BOOTSTRAP_ARGS[@]} > 0 )); then
  server_remote "$REMOTE_PROJECT_DIR/scripts/server_bootstrap.sh" "${BOOTSTRAP_ARGS[@]}"
else
  server_remote "$REMOTE_PROJECT_DIR/scripts/server_bootstrap.sh"
fi

if ! openalpha_is_true "$NO_START"; then
  if openalpha_is_true "$SERVER_DRY_RUN"; then
    server_print_command ssh "${SERVER_SSH_ARGS[@]}" "$SERVER_TARGET" \
      "$REMOTE_PROJECT_DIR/scripts/server_process.sh start all"
  else
    server_remote "$REMOTE_PROJECT_DIR/scripts/server_process.sh" start all
  fi
fi

DEPLOY_SUCCEEDED=true
DEPLOY_STOP_ATTEMPTED=false
server_remote rm -f "$REMOTE_PROJECT_DIR/.env.pre-deploy" || true
if [[ -n "$MODEL_PREVIOUS" ]]; then server_remote rm -f "$MODEL_PREVIOUS" || true; fi
if openalpha_is_true "$ROLLBACK_READY"; then
  if server_remote rm -rf "$REMOTE_ROLLBACK_DIR"; then ROLLBACK_READY=false; fi
fi
echo "Deployment completed for $SERVER_TARGET"
