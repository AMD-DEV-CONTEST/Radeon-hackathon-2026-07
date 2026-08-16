#!/usr/bin/env bash
set -euo pipefail

ROOT=/persistent/silent-core
mkdir -p "$ROOT/logs" "$ROOT/run"

start_service() {
  local name="$1"
  if [[ -f "$ROOT/run/$name.pid" ]] && kill -0 "$(cat "$ROOT/run/$name.pid")" 2>/dev/null; then
    echo "$name already running"
    return
  fi
  nohup "$ROOT/src/start_$name.sh" >"$ROOT/logs/$name.log" 2>&1 &
  echo $! >"$ROOT/run/$name.pid"
  echo "started $name pid=$(cat "$ROOT/run/$name.pid")"
}

start_service llm
start_service image
start_service tts
start_service gateway
