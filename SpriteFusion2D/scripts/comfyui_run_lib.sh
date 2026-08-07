#!/usr/bin/env bash
# comfyui_run_lib.sh -- luna-workpack R03.
#
# Shared config + helper functions for scripts/start_comfyui.sh,
# scripts/stop_comfyui.sh and scripts/status_comfyui.sh. Sourced by all
# three (never executed directly) so the three entry points cannot drift
# on: which env vars they read, how the receipt file is written/parsed, and
# how a PID is verified to actually belong to the ComfyUI instance we
# started (not some unrelated process that happens to reuse the PID).
#
# This file only defines variables and functions; it has zero side effects
# on its own, so it is safe for tests to `source` it directly (same pattern
# as scripts/setup_comfyui_radeon.sh / tests/test_setup_comfyui_radeon_shell.py).
#
# Design notes for later tasks (R04 etc.):
#
# - One receipt file per ComfyUI instance, plain `key=value` lines (no jq
#   dependency assumed on the Radeon box). The PID lives inside the receipt
#   (field `pid=`); there is deliberately no separate `.pid` file to keep in
#   sync -- the receipt IS the PID record.
# - `--listen 127.0.0.1` is hard-coded in start_comfyui.sh, NOT exposed as
#   an env var here, so no environment misconfiguration can accidentally
#   bind ComfyUI beyond loopback.
# - A PID alone is never trusted. Before start.sh treats an existing
#   receipt as "already running" and before stop.sh sends any signal, the
#   recorded PID's live command line (`/proc/<pid>/cmdline`, falling back to
#   `ps -f -p <pid>` when /proc is unavailable, e.g. non-Linux dev boxes)
#   must contain the expected venv python path, `main.py`, and
#   `--port <expected-port>` as an exact token, in that order. If it does
#   not match, the PID is treated as unrelated and is never touched.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables). Root path
# defaults match scripts/start_comfyui.sh / scripts/setup_comfyui_radeon.sh
# so the three scripts keep working together with zero extra configuration.
# ---------------------------------------------------------------------------

SPRITE_WORKSHOP_COMFY_ROOT="${SPRITE_WORKSHOP_COMFY_ROOT:-/persistent/ComfyUI}"
SPRITE_WORKSHOP_COMFY_VENV="${SPRITE_WORKSHOP_COMFY_VENV:-/persistent/comfyui-venv}"
SPRITE_WORKSHOP_ROCM_SITE="${SPRITE_WORKSHOP_ROCM_SITE:-/opt/venv/lib/python3.12/site-packages}"
SPRITE_WORKSHOP_COMFY_PORT="${SPRITE_WORKSHOP_COMFY_PORT:-8188}"

# Persistent run directory for the receipt + log file. Defaults to a sibling
# of SPRITE_WORKSHOP_COMFY_ROOT under the same persistent volume (NOT /tmp --
# this must survive across calls on a long-lived Radeon Cloud container).
SPRITE_WORKSHOP_COMFY_RUN_DIR="${SPRITE_WORKSHOP_COMFY_RUN_DIR:-$(dirname -- "$SPRITE_WORKSHOP_COMFY_ROOT")/comfyui-run}"
SPRITE_WORKSHOP_COMFY_RECEIPT_FILE="${SPRITE_WORKSHOP_COMFY_RECEIPT_FILE:-${SPRITE_WORKSHOP_COMFY_RUN_DIR}/comfyui.receipt}"
SPRITE_WORKSHOP_COMFY_LOG_FILE="${SPRITE_WORKSHOP_COMFY_LOG_FILE:-${SPRITE_WORKSHOP_COMFY_RUN_DIR}/comfyui.log}"

# Health check. Path/timeout match sprite_workshop/radeon_probe.py's own
# ComfyUI check (GET /system_stats, 5s default) so `status` and R01's probe
# agree on what "healthy" means.
SPRITE_WORKSHOP_COMFY_HEALTH_PATH="${SPRITE_WORKSHOP_COMFY_HEALTH_PATH:-/system_stats}"
SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS="${SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS:-5}"

# stop: seconds to wait after SIGTERM before escalating to SIGKILL.
SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS="${SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS:-15}"

# start: seconds to wait right after spawning before checking the process
# is still alive, to catch an instant crash-on-launch (e.g. missing
# dependency) instead of leaving behind a receipt for a dead PID. This is
# deliberately short -- it does NOT wait for the HTTP health check, because
# a real ComfyUI can take a long time to finish loading a checkpoint. Use
# status_comfyui.sh to poll for full HTTP readiness.
SPRITE_WORKSHOP_COMFY_START_GRACE_SECONDS="${SPRITE_WORKSHOP_COMFY_START_GRACE_SECONDS:-2}"

# Tag used in log/die prefixes. Entry scripts set this before sourcing.
COMFYUI_RUN_LOG_TAG="${COMFYUI_RUN_LOG_TAG:-comfyui-run}"

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

log() {
  printf '[%s] %s\n' "$COMFYUI_RUN_LOG_TAG" "$*" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "$COMFYUI_RUN_LOG_TAG" "$*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

comfy_python_bin() {
  printf '%s/bin/python' "$SPRITE_WORKSHOP_COMFY_VENV"
}

ensure_run_dir() {
  mkdir -p -- "$SPRITE_WORKSHOP_COMFY_RUN_DIR"
}

require_comfyui_installed() {
  if [[ ! -f "$SPRITE_WORKSHOP_COMFY_ROOT/main.py" ]]; then
    log "ComfyUI is not installed at $SPRITE_WORKSHOP_COMFY_ROOT"
    exit 3
  fi
  if [[ ! -x "$(comfy_python_bin)" ]]; then
    log "ComfyUI environment is not installed at $SPRITE_WORKSHOP_COMFY_VENV"
    exit 3
  fi
}

# ---------------------------------------------------------------------------
# Receipt file: plain `key=value` lines, one instance per file, written
# atomically (write to a temp file, then rename) so a reader never sees a
# half-written receipt.
# ---------------------------------------------------------------------------

receipt_read_field() {
  # receipt_read_field <file> <key> -- prints the value or returns 1 if the
  # file or key is missing.
  local file="$1" key="$2" line
  [[ -f "$file" ]] || return 1
  line="$(grep -m1 -E "^${key}=" -- "$file" || true)"
  [[ -n "$line" ]] || return 1
  printf '%s\n' "${line#*=}"
}

write_receipt() {
  # write_receipt <pid> <port>
  local pid="$1" port="$2" tmp
  ensure_run_dir
  tmp="${SPRITE_WORKSHOP_COMFY_RECEIPT_FILE}.tmp.$$"
  {
    printf 'receipt_version=1\n'
    printf 'pid=%s\n' "$pid"
    printf 'port=%s\n' "$port"
    printf 'listen_host=127.0.0.1\n'
    printf 'comfy_root=%s\n' "$SPRITE_WORKSHOP_COMFY_ROOT"
    printf 'comfy_venv=%s\n' "$SPRITE_WORKSHOP_COMFY_VENV"
    printf 'python_bin=%s\n' "$(comfy_python_bin)"
    printf 'log_file=%s\n' "$SPRITE_WORKSHOP_COMFY_LOG_FILE"
    printf 'health_path=%s\n' "$SPRITE_WORKSHOP_COMFY_HEALTH_PATH"
    printf 'started_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$tmp"
  mv -f -- "$tmp" "$SPRITE_WORKSHOP_COMFY_RECEIPT_FILE"
}

remove_receipt() {
  rm -f -- "$SPRITE_WORKSHOP_COMFY_RECEIPT_FILE"
}

# ---------------------------------------------------------------------------
# PID verification. A PID is only ever treated as "our ComfyUI" if it is
# alive AND its live command line matches the expected invocation. This is
# what prevents stop/status from acting on an unrelated process that
# happens to have inherited a recycled PID.
# ---------------------------------------------------------------------------

pid_is_running() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

pid_cmdline() {
  # Prints the live process's command line (best effort), space-joined.
  # Prefers /proc/<pid>/cmdline (exact, NUL-separated -- works on real Linux
  # Radeon boxes AND on MSYS/Git-Bash dev machines, which also expose a
  # /proc emulation). Falls back to `ps -f -p <pid>` for other platforms.
  local pid="$1"
  if [[ -r "/proc/$pid/cmdline" ]]; then
    tr '\0' ' ' < "/proc/$pid/cmdline"
    return 0
  fi
  if have_cmd ps; then
    ps -f -p "$pid" 2>/dev/null | tail -n +2
    return 0
  fi
  return 1
}

process_matches_target() {
  # process_matches_target <pid> <expected_port>
  # True only if pid is alive AND its command line contains, in order, the
  # configured venv python path, "main.py", and "--port <expected_port>" as
  # a distinct token (not just a numeric substring of a longer port).
  local pid="$1" expected_port="$2" expected_python cmdline
  pid_is_running "$pid" || return 1
  expected_python="$(comfy_python_bin)"
  cmdline="$(pid_cmdline "$pid" 2>/dev/null || true)"
  [[ -n "$cmdline" ]] || return 1
  cmdline="$cmdline "
  case "$cmdline" in
    *"$expected_python"*"main.py"*"--port ${expected_port} "*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# ---------------------------------------------------------------------------
# HTTP health check
# ---------------------------------------------------------------------------

http_health_check() {
  # http_health_check <port> -- GET http://127.0.0.1:<port><health_path>
  # with a bounded timeout. Returns curl's exit code (0 == HTTP 2xx within
  # the timeout). Never blocks longer than
  # SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS.
  local port="$1" url
  have_cmd curl || { log "curl not found; cannot perform HTTP health check"; return 127; }
  url="http://127.0.0.1:${port}${SPRITE_WORKSHOP_COMFY_HEALTH_PATH}"
  # --noproxy: this is a loopback-only check by construction (ComfyUI is
  # only ever started with --listen 127.0.0.1), so it must never be routed
  # through an http_proxy/https_proxy set in the environment.
  curl -fsS --noproxy '127.0.0.1' --max-time "$SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS" -o /dev/null "$url"
}

# ---------------------------------------------------------------------------
# Combined receipt + liveness read, shared by start/stop/status.
#
# Sets (and exports as plain shell vars in the caller's scope, since bash
# functions share the caller's variable namespace unless `local` is used):
#   RECEIPT_PID, RECEIPT_PORT   -- fields from the receipt file ("" if absent)
#   RECEIPT_PRESENT             -- 1 if the receipt file exists, else 0
#   RECEIPT_MATCHES             -- 1 if RECEIPT_PID is alive AND its cmdline
#                                   matches RECEIPT_PORT, else 0
# ---------------------------------------------------------------------------
load_receipt_state() {
  RECEIPT_PID=""
  RECEIPT_PORT=""
  RECEIPT_PRESENT=0
  RECEIPT_MATCHES=0
  if [[ -f "$SPRITE_WORKSHOP_COMFY_RECEIPT_FILE" ]]; then
    RECEIPT_PRESENT=1
    RECEIPT_PID="$(receipt_read_field "$SPRITE_WORKSHOP_COMFY_RECEIPT_FILE" pid || true)"
    RECEIPT_PORT="$(receipt_read_field "$SPRITE_WORKSHOP_COMFY_RECEIPT_FILE" port || true)"
    if [[ -n "$RECEIPT_PID" && -n "$RECEIPT_PORT" ]] && process_matches_target "$RECEIPT_PID" "$RECEIPT_PORT"; then
      RECEIPT_MATCHES=1
    fi
  fi
}
