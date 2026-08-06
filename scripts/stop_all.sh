#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/stop_ui.sh"
"$SCRIPT_DIR/stop_api.sh"
"$SCRIPT_DIR/stop_local_llm.sh"
