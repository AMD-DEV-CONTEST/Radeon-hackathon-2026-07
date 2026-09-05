#!/bin/bash
# ScrewShell Gradio UI behind the ScrewShell relay (inference coordinator) on :18090.
#
# This is the Phase 0 production wiring. The relay owns the GLOBAL llama.cpp
# LoRA switch (POST /lora-adapters) and serializes switch+generate behind one
# asyncio.Lock, which is the only safe way to hot-swap experts on a single GPU.
# The UI's in-process Orchestrator routes the query, calls engine.activate(),
# which (in relay_mode) just records the target; chat() then stamps X-Expert
# and forwards to the relay. The relay trusts that header and does the switch.
#
# Prereqs: llama-server on :8080 (preloaded btl3/cybersec/rag_n7 via --lora
# with --lora-init-without-apply) and the relay on :18090 (local-deploy/start_relay.sh).
#
# Tunnels for local viewing:
#   ssh -L 7860:127.0.0.1:7860 -p 31010 root@36.150.116.206
set -euo pipefail

ROOT=/workspace/persistent/screwshell_run
cd "$ROOT"

export MOL_BACKEND=llamacpp

# Relay endpoint (InferenceCoordinator). NO per-request LoRA, NO auth.
export MOL_LLAMACPP_URL=http://127.0.0.1:18090

# Relay mode: engine forwards to the relay and stamps X-Expert (+ the shared
# X-Relay-Token); it does NOT touch /lora-adapters itself (that is the
# coordinator's job -> avoids the P0 silent base-fallback bug from mixing
# global + per-request LoRA).
export MOL_RELAY_MODE=1

# Shared secret authenticating the UI's X-Expert header to the relay. MUST
# match RELAY_TRUST_TOKEN in start_relay.sh. Without it the relay re-routes
# every request via SkillRouter (a network client could otherwise spoof an
# expert). Change this to a real secret for any non-loopback deployment.
export RELAY_TRUST_TOKEN=screwshell-relay-devtoken

# Unset gateway-only knobs (relay has no API key and serves model "m").
unset MOL_LLAMACPP_API_KEY
unset MOL_LLAMACPP_MODEL

exec /opt/venv/bin/python -m screwshell.ui.app \
  --workspace "$ROOT/demo_workspace" \
  --base "$ROOT/models/Qwen3.6-27B-Q4_K_M.gguf" \
  --port 7860 --no-rag
