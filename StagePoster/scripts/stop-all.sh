#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

stop_pid_file() {
  local name="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    echo "$name: no PID file"
    return
  fi

  local pid
  pid="$(cat "$file")"

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$name: process already stopped"
    rm -f "$file"
    return
  fi

  echo "Stopping $name PID $pid"
  kill "$pid" 2>/dev/null || true

  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$file"
      echo "$name stopped"
      return
    fi

    sleep 1
  done

  echo "$name did not stop gracefully, sending SIGKILL"
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$file"
}

stop_pid_file \
  "Cloudflare Tunnel" \
  "$BACKEND_ROOT/run/cloudflared.pid"

stop_pid_file \
  "Go Backend" \
  "$BACKEND_ROOT/run/backend.pid"

stop_pid_file \
  "ComfyUI" \
  "$BACKEND_ROOT/run/comfyui.pid"

stop_pid_file \
  "vLLM" \
  "$BACKEND_ROOT/run/vllm.pid"

echo "All managed services stopped."
