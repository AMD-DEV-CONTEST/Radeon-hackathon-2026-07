#!/usr/bin/env bash
# start_ollama.sh — start the Ollama daemon if it is not already running.
#
# This is a convenience wrapper. On a fresh machine you usually want to run
# setup_ollama.sh once, then use this script (or your system service manager)
# to keep the daemon up.
set -euo pipefail

if pgrep -x ollama > /dev/null 2>&1; then
  echo "ollama is already running"
  exit 0
fi

echo "==> Starting ollama serve"
exec ollama serve
