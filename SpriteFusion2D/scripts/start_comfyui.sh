#!/usr/bin/env bash
# start_comfyui.sh -- luna-workpack R03.
#
# Starts ComfyUI in the background (not foreground/exec like the previous
# version of this script) and records a receipt (PID + port + paths) so
# this script, scripts/stop_comfyui.sh and scripts/status_comfyui.sh can all
# agree on which process is "the" managed ComfyUI instance.
#
# Idempotent: re-running start while a matching instance is already running
# (PID alive AND its live command line matches the expected venv
# python + main.py + --port invocation) does NOT spawn a second process --
# it logs that ComfyUI is already running and exits 0.
#
# Security-relevant default that is intentionally NOT an env var: ComfyUI is
# always started with `--listen 127.0.0.1`. There is no override for the
# listen host here, so a misconfigured environment can never bind ComfyUI
# beyond loopback through this script.
#
# See scripts/comfyui_run_lib.sh for the shared config/help variables,
# receipt file format and PID-verification logic used by all three
# start/stop/status scripts.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
COMFYUI_RUN_LOG_TAG="start-comfyui"
# shellcheck source=./comfyui_run_lib.sh
source "$SCRIPT_DIR/comfyui_run_lib.sh"

print_help() {
  cat <<EOF
Usage: $(basename "$0") [--help]

Starts ComfyUI in the background and writes a receipt file recording its
PID, port and paths. Safe to re-run: if a matching ComfyUI instance is
already running (per the receipt + a live PID/command-line check), this
does nothing and exits 0 instead of starting a second instance.

Options:
  --help   Show this message and exit.

Environment variables (all optional, defaults shown):
  SPRITE_WORKSHOP_COMFY_ROOT       ComfyUI checkout directory
                                     (default: /persistent/ComfyUI)
  SPRITE_WORKSHOP_COMFY_VENV       Independent ComfyUI venv directory
                                     (default: /persistent/comfyui-venv)
  SPRITE_WORKSHOP_ROCM_SITE        Mirrored ROCm torch site-packages reused
                                     via PYTHONPATH
                                     (default: /opt/venv/lib/python3.12/site-packages)
  SPRITE_WORKSHOP_COMFY_PORT       Listen port
                                     (default: 8188)
  SPRITE_WORKSHOP_COMFY_RUN_DIR    Persistent directory for the receipt and
                                     log file
                                     (default: \$(dirname \$SPRITE_WORKSHOP_COMFY_ROOT)/comfyui-run)
  SPRITE_WORKSHOP_COMFY_RECEIPT_FILE  Receipt file path
                                     (default: \$SPRITE_WORKSHOP_COMFY_RUN_DIR/comfyui.receipt)
  SPRITE_WORKSHOP_COMFY_LOG_FILE   ComfyUI stdout/stderr log file path
                                     (default: \$SPRITE_WORKSHOP_COMFY_RUN_DIR/comfyui.log)
  SPRITE_WORKSHOP_COMFY_START_GRACE_SECONDS
                                    Seconds to wait after spawning before
                                    confirming the process is still alive
                                    (default: 2)

Note: ComfyUI is always started with --listen 127.0.0.1; this is not
configurable via an environment variable.

See also: scripts/stop_comfyui.sh, scripts/status_comfyui.sh.
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
  require_comfyui_installed
  ensure_run_dir

  load_receipt_state
  if [[ "$RECEIPT_MATCHES" -eq 1 ]]; then
    log "ComfyUI already running (pid=$RECEIPT_PID, port=$RECEIPT_PORT); not starting a second instance"
    exit 0
  fi
  if [[ "$RECEIPT_PRESENT" -eq 1 ]]; then
    log "existing receipt at $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE does not point at a live, matching ComfyUI process; treating it as stale and replacing it"
    remove_receipt
  fi

  local port="$SPRITE_WORKSHOP_COMFY_PORT"
  local python_bin
  python_bin="$(comfy_python_bin)"

  log "starting ComfyUI: root=$SPRITE_WORKSHOP_COMFY_ROOT venv=$SPRITE_WORKSHOP_COMFY_VENV port=$port log=$SPRITE_WORKSHOP_COMFY_LOG_FILE"

  # Run in a subshell that `exec`s into python, so `$!` (captured right
  # after backgrounding) is the PID of the python process itself, not a
  # separate shell wrapping it -- exec replaces the subshell's process
  # image in place rather than forking. stdin is closed and stdout/stderr
  # redirected to the log file so start_comfyui.sh can return immediately
  # without holding a terminal open.
  (
    cd "$SPRITE_WORKSHOP_COMFY_ROOT" || exit 1
    exec env PYTHONPATH="$SPRITE_WORKSHOP_ROCM_SITE${PYTHONPATH:+:$PYTHONPATH}" \
      "$python_bin" main.py \
      --listen 127.0.0.1 \
      --port "$port" \
      --disable-auto-launch
  ) >>"$SPRITE_WORKSHOP_COMFY_LOG_FILE" 2>&1 <"/dev/null" &
  local new_pid=$!
  disown "$new_pid" 2>/dev/null || true

  write_receipt "$new_pid" "$port"

  # Short grace period to catch an instant crash-on-launch, so we do not
  # leave behind a receipt pointing at an already-dead PID. This does NOT
  # wait for HTTP readiness -- a real model load can take much longer than
  # is reasonable to block this script on; use status_comfyui.sh for that.
  sleep "$SPRITE_WORKSHOP_COMFY_START_GRACE_SECONDS"
  if ! pid_is_running "$new_pid"; then
    remove_receipt
    die "ComfyUI process (pid=$new_pid) exited within ${SPRITE_WORKSHOP_COMFY_START_GRACE_SECONDS}s of starting; see $SPRITE_WORKSHOP_COMFY_LOG_FILE for details"
  fi

  log "started ComfyUI (pid=$new_pid) listening on 127.0.0.1:$port; log: $SPRITE_WORKSHOP_COMFY_LOG_FILE; receipt: $SPRITE_WORKSHOP_COMFY_RECEIPT_FILE"
}

# Only run main when executed directly, not when sourced (e.g. by tests that
# want to call the shared helper functions from comfyui_run_lib.sh in
# isolation).
if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" ]]; then
  main "$@"
fi
