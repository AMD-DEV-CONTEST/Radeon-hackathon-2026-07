#!/bin/bash
# ScrewShell Gradio UI (roomy mode) for the W7900 box.
#
# Connects to the already-running llama-server on :8080 (started by
# run_roomy_server.sh) and hot-swaps LoRA experts in-process via /lora-adapters.
# Start the server FIRST -- if :8080 is down the UI still comes up, but every
# expert silently degrades to base.
#
# Binds to 127.0.0.1, so view it through an SSH tunnel from your machine:
#   ssh -L 7860:127.0.0.1:7860 -p 31010 root@36.150.116.206
# then open http://127.0.0.1:7860

set -euo pipefail

ROOT=/workspace/persistent/screwshell_run

cd "$ROOT"
export MOL_BACKEND=llamacpp

exec /opt/venv/bin/python -m screwshell.ui.app \
  --workspace "$ROOT/demo_workspace" \
  --base "$ROOT/models/Qwen3.6-27B-Q4_K_M.gguf" \
  --port 7860 --no-rag
