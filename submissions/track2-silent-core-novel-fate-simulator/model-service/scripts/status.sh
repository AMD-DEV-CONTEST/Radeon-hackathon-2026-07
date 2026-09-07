#!/usr/bin/env bash
set -euo pipefail

ROOT=/persistent/silent-core
for name in llm image tts gateway; do
  pid_file="$ROOT/run/$name.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "$name running pid=$(cat "$pid_file")"
  else
    echo "$name stopped"
  fi
done

curl --silent --show-error http://127.0.0.1:18000/health || true
echo
