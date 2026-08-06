#!/usr/bin/env bash
# Launch the resident Z-Image-Turbo image service (diary image enrichment).
#
# Runs in the ai-toolkit env (.venv_aitk) — SEPARATE from the diary .venv. The diary
# server only talks HTTP to this service; it never imports ai-toolkit/diffusers.
#
# VRAM: Z-Image ~14-18GB (gfx1100 / ROCm 7.2.1) + llama-server ~20GB + mmproj ~0.9GB
#       < 51.5GB. expandable_segments avoids fragmentation OOM under the shared GPU.
set -euo pipefail

ROOT="/home/pdfexe/dataset"
VENV="$ROOT/.venv_aitk"
export PYTHONPATH="$ROOT/tools/ai-toolkit"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export ZIMAGE_PORT="${ZIMAGE_PORT:-8090}"

# Optional person LoRA (Phase C). Leave unset for the generic MVP service.
# export ZIMAGE_LORA="$ROOT/data/zimage_lora/output_v2/zimage_meizi_pilot8_v2/zimage_meizi_pilot8_v2.safetensors"
# export ZIMAGE_LORA_SCALE="1.0"

cd "$(dirname "$0")/.."   # run from the voiceEngine repo root

# Background the resident server with nohup and return, so the launching shell can
# exit while the server (and its loaded model) keep running. The harness reaps only
# background-task process groups, so launch this via a normal foreground command.
LOG="${ZIMAGE_LOG:-/tmp/zimage_service.log}"
echo "Starting Z-Image service (log: $LOG)"
nohup "$VENV/bin/python" image/service.py > "$LOG" 2>&1 &
echo "pid $!"
