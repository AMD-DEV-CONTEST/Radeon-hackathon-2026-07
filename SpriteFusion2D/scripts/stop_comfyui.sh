#!/usr/bin/env bash
# stop_comfyui.sh -- luna-workpack R03.
#
# Stops the ComfyUI instance recorded in the receipt file written by
# scripts/start_comfyui.sh -- and ONLY that instance. Before sending any
# signal, this script re-verifies that the recorded PID is still alive AND
# that its live command line still matches the expected venv
# python + main.py + --port invocation (see comfyui_run_lib.sh
# process_matches_target). If the PID does not match (e.g. it exited and
# the number was reused by an unrelated process), this script refuses to
# touch it and exits non-zero instead of silently doing nothing or, worse,
# killing an unrelated process.
#
# Idempotent: running stop when nothing is running (no receipt, or a stale
# receipt whose PID is already dead) exits 0 and cleans up the stale
# receipt without treating that as an error.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
COMFYUI_RUN_LOG_TAG="stop-comfyui"
# shellcheck source=./comfyui_run_lib.sh
source "$SCRIPT_DIR/comfyui_run_lib.sh"

print_help() {
  cat <<EOF
Usage: $(basename "$0") [--help]

Stops the ComfyUI instance recorded in the receipt file, but only after
re-verifying the recorded PID is alive and its live command line still
matches the expected ComfyUI invocation (venv python + main.py +
--port <port>). Sends SIGTERM, waits up to
SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS, then escalates to SIGKILL if
still alive. Removes the receipt file once the process is confirmed gone.

If there is no receipt, or the receipt's PID is already dead, this exits 0
(nothing to do). If the receipt's PID is alive but its command line does
NOT match (likely PID reuse by an unrelated process), this refuses to send
any signal and exits 1, leaving the receipt in place for inspection.

Options:
  --help   Show this message and exit.

Environment variables (all optional, defaults shown):
  SPRITE_WORKSHOP_COMFY_ROOT       ComfyUI checkout directory
                                     (default: /persistent/ComfyUI)
  SPRITE_WORKSHOP_COMFY_VENV       Independent ComfyUI venv directory
                                     (default: /persistent/comfyui-venv)
  SPRITE_WORKSHOP_COMFY_RUN_DIR    Persistent directory holding the receipt
                                     (default: \$(dirname \$SPRITE_WORKSHOP_COMFY_ROOT)/comfyui-run)
  SPRITE_WORKSHOP_COMFY_RECEIPT_FILE  Receipt file path
                                     (default: \$SPRITE_WORKSHOP_COMFY_RUN_DIR/comfyui.receipt)
  SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS
                                    Seconds to wait after SIGTERM before
                                    escalating to SIGKILL
                                    (default: 15)

See also: scripts/start_comfyui.sh, scripts/status_comfyui.sh.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help | -h)
        print_help
        exit 0
        ;;
      *)
        die "unknown argument: $1 (see --help)"
        ;;
    esac
  done
}

wait_for_pid_exit() {
  # wait_for_pid_exit <pid> <timeout_seconds> -- polls every 0.2s, returns 0
  # once the PID is no longer running, 1 if it is still alive after the
  # timeout.
  local pid="$1" timeout="$2" iterations elapsed_units
  iterations=$((timeout * 5))
  [[ "$iterations" -gt 0 ]] || iterations=1
  for ((elapsed_units = 0; elapsed_units < iterations; elapsed_units++)); do
    pid_is_running "$pid" || return 0
    sleep 0.2
  done
  ! pid_is_running "$pid"
}

main() {
  parse_args "$@"

  load_receipt_state

  if [[ "$RECEIPT_PRESENT" -eq 0 ]]; then
    log "no receipt found at $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE; nothing to stop"
    exit 0
  fi

  if [[ -z "$RECEIPT_PID" ]]; then
    log "receipt at $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE has no pid field; removing it and treating as nothing to stop"
    remove_receipt
    exit 0
  fi

  if ! pid_is_running "$RECEIPT_PID"; then
    log "recorded pid $RECEIPT_PID is not running; removing stale receipt"
    remove_receipt
    exit 0
  fi

  if [[ "$RECEIPT_MATCHES" -ne 1 ]]; then
    log "pid $RECEIPT_PID is running but its command line does NOT match the expected ComfyUI invocation (root=$SPRITE_WORKSHOP_COMFY_ROOT venv=$SPRITE_WORKSHOP_COMFY_VENV port=$RECEIPT_PORT) -- refusing to signal it, this is likely PID reuse by an unrelated process. Receipt left in place at $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE for inspection."
    exit 1
  fi

  log "stopping ComfyUI (pid=$RECEIPT_PID, port=$RECEIPT_PORT): sending SIGTERM"
  kill -TERM "$RECEIPT_PID" 2>/dev/null || true

  if wait_for_pid_exit "$RECEIPT_PID" "$SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS"; then
    log "ComfyUI (pid=$RECEIPT_PID) stopped after SIGTERM"
  else
    log "ComfyUI (pid=$RECEIPT_PID) still alive after ${SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS}s; escalating to SIGKILL"
    kill -KILL "$RECEIPT_PID" 2>/dev/null || true
    if ! wait_for_pid_exit "$RECEIPT_PID" 5; then
      die "ComfyUI (pid=$RECEIPT_PID) did not exit even after SIGKILL; leaving receipt in place for manual investigation"
    fi
    log "ComfyUI (pid=$RECEIPT_PID) stopped after SIGKILL"
  fi

  remove_receipt
  log "removed receipt $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE"
}

if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" ]]; then
  main "$@"
fi
