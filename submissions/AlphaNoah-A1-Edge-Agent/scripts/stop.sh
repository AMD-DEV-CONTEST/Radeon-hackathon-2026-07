#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
if ! is_running; then rm -f "$PID_FILE"; echo "AlphaNoah is stopped."; exit 0; fi
pid="$(<"$PID_FILE")"; kill "$pid"
for _ in {1..40}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
kill -0 "$pid" 2>/dev/null && { echo "AlphaNoah did not stop cleanly."; exit 1; }
rm -f "$PID_FILE"; echo "AlphaNoah stopped."
