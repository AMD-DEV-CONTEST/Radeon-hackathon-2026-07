#!/usr/bin/env bash
set -u

RC_TUNNEL="${HOME}/.local/bin/rc-tunnel"
PORT="${BRANDPILOT_DEMO_PORT:-8000}"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}/brandpilot-radeon-demo-${UID}"
PID_FILE="${RUNTIME_DIR}/uvicorn.pid"

if [ -x "$RC_TUNNEL" ]; then
  "$RC_TUNNEL" stop >/dev/null 2>&1 || true
fi

if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if printf '%s' "$pid" | grep -Eq '^[0-9]+$' && kill -0 "$pid" 2>/dev/null; then
    command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    if printf '%s' "$command_line" | grep -Fq "uvicorn app.main:app" &&
      printf '%s' "$command_line" | grep -Fq -- "--port ${PORT}"; then
      kill "$pid"
      for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      kill -0 "$pid" 2>/dev/null && kill -TERM "$pid" 2>/dev/null || true
    fi
  fi
fi

rm -f -- "$PID_FILE" "${RUNTIME_DIR}/tunnel-url" "${RUNTIME_DIR}/uvicorn.log"
rmdir -- "$RUNTIME_DIR" 2>/dev/null || true
unset DEMO_AUTH_TOKEN

printf '%s\n' "official tunnel: stopped"
printf '%s\n' "loopback backend: stopped"
printf '%s\n' "temporary runtime state: cleared"
