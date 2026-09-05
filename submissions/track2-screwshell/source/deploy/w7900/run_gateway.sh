#!/bin/bash
# ScrewShell gateway bring-up (replaces manual run_roomy_server.sh + manual relay).
#
# One command owns the whole stack: llama-server (fit-derived ctx/ngl) + the
# ScrewShell relay (MoL gateway) on :18090. Uses screwshell.gateway.cli which
# runs: resolve config -> prelaunch port check -> setsid daemon llama-server
# -> wait /health -> launch relay. Prelaunch refuses to start (non-zero exit,
# no silent proceed) if :8080 / :18090 are already occupied.
#
# Rollback: copy run_roomy_server.sh.bak back over this file and start the UI
# against :8080 directly (see RUNBOOK.md §4). This script does NOT delete the
# manual path — it is kept as run_roomy_server.sh.bak.

set -euo pipefail

ROOT=/workspace/persistent/screwshell_run
VENV=/opt/venv/bin/python
LLAMA=/opt/llama.cpp/build/bin/llama-server

cd "$ROOT"
# cli.py defaults OBSERV_DIR to os.path.join(os.getcwd(), "screwshell_run", "observ").
# Since cwd is already $ROOT (.../screwshell_run), that adds an extra directory;
# point at the existing /workspace/persistent/screwshell_run/observ history directly.
export OBSERV_DIR="$ROOT/observ"
export MOL_BACKEND=llamacpp

# llama-fit-params lives next to llama-server in the same build dir.
export PATH="$(dirname "$LLAMA"):$PATH"

# P1 TTFT tuning (2026-08-05): ctx-size 131072 -> 98304 to free KV headroom.
# flash-attn on / cache-type-k+v q8_0 / parallel 2 are applied on the production
# standalone launcher (_llama_cmd_metrics.sh); screwshell.gateway.cli does not
# yet expose those flags as args, so they are intentionally not added here.
exec "$VENV" -m screwshell.gateway.cli \
  --model "$ROOT/models/Qwen3.6-27B-Q4_K_M.gguf" \
  --loras "$ROOT/loras/btl3/adapter.gguf,$ROOT/loras/cybersec/adapter.gguf,$ROOT/loras/rag_n7/adapter.gguf" \
  --host 127.0.0.1 --port 8080 \
  --vram-gb 48 \
  --ctx-size 98304 \
  --reasoning-budget 4096 \
  --threads 24 \
  --llama-binary "$LLAMA" \
  --llama-log "$ROOT/llama_server.log" \
  --relay-log "$ROOT/relay.log" \
  --relay-bind 127.0.0.1 \
  --metrics \
  --json
