#!/usr/bin/env bash
# Canonical AMD Radeon Cloud persistent-volume layout.
set -euo pipefail

export BG_PVC="${BG_PVC:-/persistent/BuildGuard-Radeon-backup}"
export BG_REPO="${BG_REPO:-$BG_PVC}"
export BG_ENVS="${BG_ENVS:-$BG_PVC/envs}"
export BG_VENV="${BG_VENV:-$BG_ENVS/app-py312-rocm721}"
export BG_MODELS="${BG_MODELS:-$BG_PVC/models}"
export BG_DATASETS="${BG_DATASETS:-$BG_PVC/data}"
export BG_WORKSPACE="${BG_WORKSPACE:-$BG_PVC/workspace}"
export BG_RUNTIME="${BG_RUNTIME:-$BG_PVC/runtime}"
export BG_ARTIFACTS="${BG_ARTIFACTS:-$BG_PVC/artifacts}"
export BG_LOGS="${BG_LOGS:-$BG_PVC/logs}"
export BG_RUN="${BG_RUN:-$BG_PVC/run}"
export BG_CONFIG="${BG_CONFIG:-$BG_REPO/configs/competition/app.yaml}"

mkdir -p "$BG_ENVS" "$BG_MODELS" "$BG_DATASETS" "$BG_WORKSPACE" \
  "$BG_RUNTIME" "$BG_ARTIFACTS" "$BG_LOGS" "$BG_RUN"

export HF_HOME="${HF_HOME:-$BG_MODELS/huggingface-cache}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost,::1}"

if [[ -d "$BG_VENV" ]]; then
  export PATH="$BG_VENV/bin:$PATH"
fi
