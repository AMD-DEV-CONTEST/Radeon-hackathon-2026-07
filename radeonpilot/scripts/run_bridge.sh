#!/usr/bin/env bash
# Start the localhost Pi bridge multi-agent service.
set -euo pipefail
cd "$(dirname "$0")/../pi-bridge"
NODE_BIN="${PI_NODE_BIN:-node}"
export VLLM_BASE_URL="${VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
export VLLM_PID="${VLLM_PID:-}"
exec "$NODE_BIN" src/server.mjs
