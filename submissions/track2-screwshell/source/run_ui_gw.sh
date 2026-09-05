#!/bin/bash
# ScrewShell Gradio UI behind the llama-swap gateway (peers mode, POC).
#
# Same as run_ui.sh but the UI talks to llama-swap on :18080 instead of the
# raw llama-server on :8080. This exercises the gateway contract: API key
# injection + gateway model id (NOT the bare "m" the direct backend uses).
#
# Bring up the gateway first:
#   llama-swap --listen 127.0.0.1:18080 --config /opt/llama-swap/poc/ls_phase2.yaml
#
# Then tunnel the gateway port to your machine:
#   ssh -L 18080:127.0.0.1:18080 -p 31010 root@36.150.116.206
# and the UI port:
#   ssh -L 7860:127.0.0.1:7860   -p 31010 root@36.150.116.206
#
# SECURITY: screwshell-poc is the POC key baked into the gateway config. Rotate
# it and move to a real secret store before any non-POC use (gateway review P0.6).

set -euo pipefail

ROOT=/workspace/persistent/screwshell_run

cd "$ROOT"
export MOL_BACKEND=llamacpp

# Gateway endpoint (llama-swap, peers mode).
export MOL_LLAMACPP_URL=http://127.0.0.1:18080

# Gateway auth. Empty => no Authorization header (direct-server mode).
export MOL_LLAMACPP_API_KEY=screwshell-poc

# Gateway model id. managed mode uses the clean alias (peers mode used the
# full GGUF path). Unset => "m" (valid only against a direct llama-server).
export MOL_LLAMACPP_MODEL='screwshell-qwen3.6-27b'

exec /opt/venv/bin/python -m screwshell.ui.app \
  --workspace "$ROOT/demo_workspace" \
  --base "$ROOT/models/Qwen3.6-27B-Q4_K_M.gguf" \
  --port 7860 --no-rag
