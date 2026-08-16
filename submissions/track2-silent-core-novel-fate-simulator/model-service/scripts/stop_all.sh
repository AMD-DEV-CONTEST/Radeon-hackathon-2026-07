#!/usr/bin/env bash
set -euo pipefail

ROOT=/persistent/silent-core
for name in gateway tts image llm; do
  pid_file="$ROOT/run/$name.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      echo "stopped $name pid=$pid"
    fi
    rm -f "$pid_file"
  fi
done
