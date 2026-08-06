#!/usr/bin/env bash
# status_comfyui.sh -- luna-workpack R03.
#
# Reports the status of the ComfyUI instance recorded in the receipt file,
# checking BOTH:
#   1. the recorded PID is alive and its live command line still matches
#      the expected venv python + main.py + --port invocation, and
#   2. an HTTP GET against 127.0.0.1:<port><health_path> succeeds within a
#      bounded timeout (default /system_stats, 5s -- same endpoint/timeout
#      as sprite_workshop/radeon_probe.py's own ComfyUI check).
#
# This script is read-only: it never sends a signal and never deletes the
# receipt file, even when it detects a stale/mismatched receipt -- use
# stop_comfyui.sh for that.
#
# Prints a `status=<value>` line to stdout for easy scripting/grepping, and
# human-readable detail to stderr (same log()/die() convention as the other
# R02/R03 scripts). Exit codes:
#   0  running     -- pid matches AND http health check succeeded
#   1  stopped     -- no receipt file at all
#   2  unhealthy   -- pid matches but the HTTP health check failed/timed out
#                     (e.g. still loading, or hung)
#   3  stale       -- a receipt exists but its pid is dead, or alive with a
#                     non-matching command line (likely PID reuse)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
COMFYUI_RUN_LOG_TAG="status-comfyui"
# shellcheck source=./comfyui_run_lib.sh
source "$SCRIPT_DIR/comfyui_run_lib.sh"

print_help() {
  cat <<EOF
Usage: $(basename "$0") [--help]

Reports whether the ComfyUI instance recorded in the receipt file is
running, by checking both the recorded PID's liveness/command-line and an
HTTP health probe against 127.0.0.1:<port><health_path>. Read-only: never
signals a process or deletes the receipt.

Prints "status=<running|stopped|unhealthy|stale>" plus detail fields to
stdout. Exit codes: 0=running, 1=stopped (no receipt), 2=unhealthy (pid ok,
HTTP failed), 3=stale (receipt present but pid dead or mismatched).

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
  SPRITE_WORKSHOP_COMFY_HEALTH_PATH   HTTP path probed for health
                                     (default: /system_stats)
  SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS
                                    HTTP health check timeout
                                    (default: 5)

See also: scripts/start_comfyui.sh, scripts/stop_comfyui.sh.
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

main() {
  parse_args "$@"

  load_receipt_state

  if [[ "$RECEIPT_PRESENT" -eq 0 ]]; then
    log "no receipt at $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE"
    printf 'status=stopped\n'
    printf 'receipt=%s\n' "$SPRITE_WORKSHOP_COMFY_RECEIPT_FILE"
    exit 1
  fi

  if [[ "$RECEIPT_MATCHES" -ne 1 ]]; then
    log "receipt at $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE does not point at a live, matching ComfyUI process (pid=${RECEIPT_PID:-<missing>}, port=${RECEIPT_PORT:-<missing>}); run stop_comfyui.sh to clean it up"
    printf 'status=stale\n'
    printf 'pid=%s\n' "${RECEIPT_PID:-}"
    printf 'port=%s\n' "${RECEIPT_PORT:-}"
    printf 'receipt=%s\n' "$SPRITE_WORKSHOP_COMFY_RECEIPT_FILE"
    exit 3
  fi

  if http_health_check "$RECEIPT_PORT"; then
    log "ComfyUI running and healthy (pid=$RECEIPT_PID, port=$RECEIPT_PORT)"
    printf 'status=running\n'
    printf 'pid=%s\n' "$RECEIPT_PID"
    printf 'port=%s\n' "$RECEIPT_PORT"
    printf 'health_url=http://127.0.0.1:%s%s\n' "$RECEIPT_PORT" "$SPRITE_WORKSHOP_COMFY_HEALTH_PATH"
    exit 0
  fi

  log "ComfyUI process matches (pid=$RECEIPT_PID, port=$RECEIPT_PORT) but HTTP health check against http://127.0.0.1:${RECEIPT_PORT}${SPRITE_WORKSHOP_COMFY_HEALTH_PATH} failed within ${SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS}s"
  printf 'status=unhealthy\n'
  printf 'pid=%s\n' "$RECEIPT_PID"
  printf 'port=%s\n' "$RECEIPT_PORT"
  printf 'health_url=http://127.0.0.1:%s%s\n' "$RECEIPT_PORT" "$SPRITE_WORKSHOP_COMFY_HEALTH_PATH"
  exit 2
}

if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" ]]; then
  main "$@"
fi
