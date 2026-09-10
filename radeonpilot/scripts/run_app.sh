#!/usr/bin/env bash
# Start the Gradio Ops Console.
set -euo pipefail
cd "$(dirname "$0")/.."
export RADEONPILOT_MODE="${RADEONPILOT_MODE:-demo}"
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
exec python app.py
