#!/usr/bin/env bash
set -euo pipefail

bg_read_pid() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(tr -d '[:space:]' < "$pid_file")"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s\n' "$pid"
}

bg_stop_pid() {
  local pid_file="$1" expected="$2" timeout="${3:-30}" pid
  pid="$(bg_read_pid "$pid_file")" || {
    rm -f -- "$pid_file"
    return 0
  }
  local command
  command="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$command" == *"$expected"* ]] || {
    echo "Refusing to stop PID $pid: expected '$expected', got '$command'" >&2
    return 1
  }
  kill -TERM "$pid"
  for _ in $(seq 1 "$timeout"); do
    kill -0 "$pid" 2>/dev/null || {
      rm -f -- "$pid_file"
      return 0
    }
    sleep 1
  done
  kill -KILL "$pid"
  rm -f -- "$pid_file"
}

bg_require_free_port() {
  local port="$1"
  if ss -lnt 2>/dev/null | grep -Eq ":${port}[[:space:]]"; then
    echo "Port $port is already in use" >&2
    return 1
  fi
}
