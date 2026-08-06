#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_config
if is_running; then echo "AlphaNoah: RUNNING (PID $(<"$PID_FILE"))"; echo "URL: http://127.0.0.1:$ALPHANOAH_PORT"; else echo "AlphaNoah: STOPPED"; exit 1; fi
