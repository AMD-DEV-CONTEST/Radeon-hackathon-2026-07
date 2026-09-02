#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"
openalpha_load_env "$ROOT_DIR" runtime required

: "${OPENALPHA_ROOT:=$ROOT_DIR}"
: "${OPENALPHA_RUN_DIR:=$OPENALPHA_ROOT/data/run}"
: "${OPENALPHA_LOG_DIR:=$OPENALPHA_ROOT/data/logs}"
: "${SERVER_SERVICE_MODE:=auto}"
: "${SERVER_START_COMPONENTS:=llama,api,worker}"
: "${SERVER_START_TIMEOUT:=180}"
: "${SERVER_STOP_TIMEOUT:=20}"
: "${SERVER_LOCK_TIMEOUT:=30}"

if [[ "$OPENALPHA_ROOT" != "$ROOT_DIR" ]]; then
  echo "OPENALPHA_ROOT ($OPENALPHA_ROOT) must match $ROOT_DIR." >&2
  exit 1
fi
for timeout_name in SERVER_START_TIMEOUT SERVER_STOP_TIMEOUT SERVER_LOCK_TIMEOUT; do
  timeout_value="${!timeout_name}"
  if [[ ! "$timeout_value" =~ ^[0-9]+$ ]] || (( timeout_value < 1 )); then
    echo "$timeout_name must be a positive integer: $timeout_value" >&2
    exit 1
  fi
done

mkdir -p "$OPENALPHA_RUN_DIR" "$OPENALPHA_LOG_DIR"

systemd_online() {
  command -v systemctl >/dev/null 2>&1 \
    && [[ -d /run/systemd/system ]] \
    && systemctl show-environment >/dev/null 2>&1
}

service_mode() {
  case "$SERVER_SERVICE_MODE" in
    process|nohup) echo process ;;
    systemd)
      if ! systemd_online; then
        echo "SERVER_SERVICE_MODE=systemd but systemd is offline." >&2
        return 1
      fi
      echo systemd
      ;;
    auto)
      if systemd_online && [[ -x /usr/local/bin/openalpha-service ]]; then
        echo systemd
      else
        echo process
      fi
      ;;
    *) echo "Unsupported SERVER_SERVICE_MODE: $SERVER_SERVICE_MODE" >&2; return 1 ;;
  esac
}

configured_components() {
  local raw="$SERVER_START_COMPONENTS"
  local item
  IFS=',' read -r -a items <<< "$raw"
  for item in "${items[@]}"; do
    item="${item//[[:space:]]/}"
    case "$item" in
      llama|api|worker) printf '%s\n' "$item" ;;
      '') ;;
      *) echo "Unsupported component in SERVER_START_COMPONENTS: $item" >&2; return 1 ;;
    esac
  done
}

component_selected() {
  local requested="$1"
  local component
  while IFS= read -r component; do
    [[ "$component" == "$requested" ]] && return 0
  done <<< "$CONFIGURED_COMPONENTS_TEXT"
  return 1
}

pid_file() { printf '%s/%s.pid\n' "$OPENALPHA_RUN_DIR" "$1"; }
log_file() { printf '%s/%s.log\n' "$OPENALPHA_LOG_DIR" "$1"; }

process_start_time() {
  local pid="$1"
  [[ -r "/proc/$pid/stat" ]] || return 1
  awk '{print $22}' "/proc/$pid/stat"
}

process_state() {
  local pid="$1"
  [[ -r "/proc/$pid/stat" ]] || return 1
  awk '{print $3}' "/proc/$pid/stat"
}

read_valid_pid() {
  local component="$1"
  local file
  local pid
  local recorded_start
  local actual_start
  file="$(pid_file "$component")"
  [[ -f "$file" ]] || return 1
  read -r pid recorded_start < "$file" || return 1
  [[ "$pid" =~ ^[0-9]+$ && "$recorded_start" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [[ "$(process_state "$pid")" != Z ]] || return 1
  actual_start="$(process_start_time "$pid")" || return 1
  [[ "$actual_start" == "$recorded_start" ]] || return 1
  printf '%s\n' "$pid"
}

remove_stale_pid() {
  local component="$1"
  if ! read_valid_pid "$component" >/dev/null; then
    rm -f "$(pid_file "$component")" || return 1
  fi
}

component_command() {
  local component="$1"
  case "$component" in
    llama) COMPONENT_COMMAND=("$OPENALPHA_ROOT/scripts/start_rocm_llama.sh") ;;
    api) COMPONENT_COMMAND=("$OPENALPHA_ROOT/.venv/bin/openalpha" serve) ;;
    worker) COMPONENT_COMMAND=("$OPENALPHA_ROOT/.venv/bin/openalpha" worker) ;;
    *) echo "Unknown component: $component" >&2; return 2 ;;
  esac
}

_start_process_component() {
  local component="$1"
  local pid
  local started
  local logfile
  remove_stale_pid "$component" || return 1
  if pid="$(read_valid_pid "$component")"; then
    echo "$component already running (pid $pid)"
    return 0
  fi
  component_command "$component" || return 1
  logfile="$(log_file "$component")"
  if ! printf '\n[%s] starting %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$component" >> "$logfile"; then
    echo "Could not write the $component log: $logfile" >&2
    return 1
  fi
  (
    cd "$OPENALPHA_ROOT"
    exec nohup "${COMPONENT_COMMAND[@]}" >> "$logfile" 2>&1 </dev/null
  ) &
  pid=$!
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$component failed to start; recent log output:" >&2
    tail -n 40 "$logfile" >&2 || true
    return 1
  fi
  if [[ "$(process_state "$pid")" == Z ]]; then
    echo "$component exited during startup; recent log output:" >&2
    tail -n 40 "$logfile" >&2 || true
    return 1
  fi
  if ! started="$(process_start_time "$pid")"; then
    kill -TERM "$pid" 2>/dev/null || true
    echo "Could not read the $component process start time." >&2
    return 1
  fi
  if ! printf '%s %s\n' "$pid" "$started" > "$(pid_file "$component")"; then
    kill -TERM "$pid" 2>/dev/null || true
    echo "Could not write the $component PID file." >&2
    return 1
  fi
  echo "$component started (pid $pid, log $logfile)"
}

_stop_process_component() {
  local component="$1"
  local pid
  local elapsed=0
  if ! pid="$(read_valid_pid "$component")"; then
    rm -f "$(pid_file "$component")"
    echo "$component already stopped"
    return 0
  fi
  if ! kill -TERM "$pid"; then
    echo "Could not signal $component (pid $pid); retaining its PID file." >&2
    return 1
  fi
  while read_valid_pid "$component" >/dev/null 2>&1 && (( elapsed < SERVER_STOP_TIMEOUT )); do
    sleep 1
    elapsed=$((elapsed + 1))
  done
  if read_valid_pid "$component" >/dev/null 2>&1; then
    echo "$component did not stop after ${SERVER_STOP_TIMEOUT}s; sending SIGKILL" >&2
    if ! kill -KILL "$pid"; then
      echo "Could not kill $component (pid $pid); retaining its PID file." >&2
      return 1
    fi
  fi
  rm -f "$(pid_file "$component")" || return 1
  echo "$component stopped"
}

with_component_lock() {
  local callback="$1"
  local component="$2"
  local lock_dir="$OPENALPHA_RUN_DIR/$component.lock"
  local owner_pid=""
  local elapsed=0
  local status=0

  while ! mkdir "$lock_dir" 2>/dev/null; do
    owner_pid=""
    if [[ -f "$lock_dir/owner" ]]; then
      read -r owner_pid < "$lock_dir/owner" || owner_pid=""
    fi
    if [[ "$owner_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$owner_pid" 2>/dev/null; then
      if ! rm -f "$lock_dir/owner"; then return 1; fi
      rmdir "$lock_dir" 2>/dev/null || true
      continue
    fi
    if (( elapsed >= SERVER_LOCK_TIMEOUT )); then
      if [[ "$owner_pid" =~ ^[0-9]+$ ]]; then
        echo "Timed out waiting for the $component lifecycle lock." >&2
        return 1
      fi
      # An ownerless directory can remain after a crash between mkdir and the
      # owner write. Wait a full timeout before reclaiming it to avoid stealing
      # a newly-created lock from a descheduled process.
      if ! rm -f "$lock_dir/owner"; then return 1; fi
      rmdir "$lock_dir" 2>/dev/null || true
      elapsed=0
      continue
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  if ! printf '%s\n' "$$" > "$lock_dir/owner"; then
    rmdir "$lock_dir" 2>/dev/null || true
    echo "Could not initialize the $component lifecycle lock." >&2
    return 1
  fi
  "$callback" "$component" || status=$?
  if ! rm -f "$lock_dir/owner"; then status=1; fi
  rmdir "$lock_dir" 2>/dev/null || true
  return "$status"
}

start_process_component() {
  with_component_lock _start_process_component "$1"
}

stop_process_component() {
  with_component_lock _stop_process_component "$1"
}

health_url() {
  case "$1" in
    llama) printf '%s/models\n' "${OPENALPHA_LLAMA_URL%/}" ;;
    api) printf 'http://127.0.0.1:%s/api/health\n' "${OPENALPHA_PORT:-8765}" ;;
    *) return 1 ;;
  esac
}

check_url() {
  local url="$1"
  "$OPENALPHA_ROOT/.venv/bin/python" - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
    if response.status >= 400:
        raise SystemExit(1)
PY
}

wait_for_health() {
  local component="$1"
  local url
  local elapsed=0
  url="$(health_url "$component")"
  while (( elapsed < SERVER_START_TIMEOUT )); do
    if check_url "$url"; then
      echo "$component health check passed: $url"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "$component did not become healthy within ${SERVER_START_TIMEOUT}s: $url" >&2
  tail -n 60 "$(log_file "$component")" >&2 || true
  return 1
}

unit_for_component() {
  printf 'openalpha-%s.service\n' "$1"
}

start_component() {
  local mode="$1"
  local component="$2"
  if [[ "$mode" == systemd ]]; then
    if ! systemctl start "$(unit_for_component "$component")"; then return 1; fi
  else
    if ! start_process_component "$component"; then return 1; fi
  fi
  if [[ "$component" == llama || "$component" == api ]]; then
    if ! wait_for_health "$component"; then
      stop_component "$mode" "$component" || true
      return 1
    fi
  fi
  return 0
}

stop_component() {
  local mode="$1"
  local component="$2"
  if [[ "$mode" == systemd ]]; then
    systemctl stop "$(unit_for_component "$component")"
  else
    stop_process_component "$component"
  fi
}

status_component() {
  local mode="$1"
  local component="$2"
  local pid
  if [[ "$mode" == systemd ]]; then
    if systemctl is-active --quiet "$(unit_for_component "$component")"; then
      echo "$component: RUNNING (systemd)"
      return 0
    fi
    echo "$component: STOPPED (systemd)"
    return 1
  fi
  if pid="$(read_valid_pid "$component")"; then
    echo "$component: RUNNING (pid $pid, log $(log_file "$component"))"
    return 0
  fi
  remove_stale_pid "$component"
  echo "$component: STOPPED"
  return 1
}

start_all() {
  local mode="$1"
  local component
  local failed=0
  for component in llama api worker; do
    if component_selected "$component"; then
      start_component "$mode" "$component" || failed=1
    fi
  done
  return "$failed"
}

stop_all() {
  local mode="$1"
  local component
  local failed=0
  for component in worker api llama; do
    stop_component "$mode" "$component" || failed=1
  done
  return "$failed"
}

show_status() {
  local mode="$1"
  local component
  local failed=0
  echo "service_mode=$mode"
  echo "project=$OPENALPHA_ROOT"
  echo "data=${OPENALPHA_DATA_DIR:-$OPENALPHA_ROOT/data/runtime}"
  for component in llama api worker; do
    if status_component "$mode" "$component"; then
      if ! component_selected "$component"; then
        echo "warning: $component is running but is not in SERVER_START_COMPONENTS" >&2
      fi
    elif component_selected "$component"; then
      failed=1
    fi
  done
  df -h "$OPENALPHA_ROOT" | tail -n 1 || true
  return "$failed"
}

ACTION="${1:-status}"
REQUESTED_COMPONENT="${2:-all}"
MODE="$(service_mode)"
CONFIGURED_COMPONENTS_TEXT="$(configured_components)"

if [[ "$REQUESTED_COMPONENT" != all ]]; then
  case "$REQUESTED_COMPONENT" in llama|api|worker) ;; *) echo "Unknown component: $REQUESTED_COMPONENT" >&2; exit 2 ;; esac
fi

case "$ACTION" in
  start)
    if [[ "$REQUESTED_COMPONENT" == all ]]; then start_all "$MODE"; else start_component "$MODE" "$REQUESTED_COMPONENT"; fi
    ;;
  stop)
    if [[ "$REQUESTED_COMPONENT" == all ]]; then stop_all "$MODE"; else stop_component "$MODE" "$REQUESTED_COMPONENT"; fi
    ;;
  restart)
    if [[ "$REQUESTED_COMPONENT" == all ]]; then
      stop_all "$MODE"
      start_all "$MODE"
    else
      stop_component "$MODE" "$REQUESTED_COMPONENT"
      start_component "$MODE" "$REQUESTED_COMPONENT"
    fi
    ;;
  status)
    if [[ "$REQUESTED_COMPONENT" == all ]]; then
      show_status "$MODE"
    else
      status_component "$MODE" "$REQUESTED_COMPONENT"
    fi
    ;;
  *) echo "Usage: $0 start|stop|restart|status [all|llama|api|worker]" >&2; exit 2 ;;
esac
