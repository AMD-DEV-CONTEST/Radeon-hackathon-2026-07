#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PERSISTENCE_ROOT="${PERSISTENCE_ROOT:-${SV_ROOT:-/workspace/persistent/silent-vision}}"
export SV_ROOT="${SV_ROOT:-$PERSISTENCE_ROOT}"
export TORCH_HOME="${TORCH_HOME:-$PERSISTENCE_ROOT/cache/torch}"
export PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
export COMMAND_BACKEND="${COMMAND_BACKEND:-torch}"
export COMMAND_CLASSIFIER_CHECKPOINT="${COMMAND_CLASSIFIER_CHECKPOINT:-$PERSISTENCE_ROOT/models/fixed-phrase.pt}"
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-*}"

if [[ "$COMMAND_BACKEND" != "torch" && "$COMMAND_BACKEND" != "prototype" ]]; then
  echo "COMMAND_BACKEND must be torch or prototype recording mode" >&2
  exit 1
fi
if [[ "$COMMAND_BACKEND" == "torch" && ! -s "$COMMAND_CLASSIFIER_CHECKPOINT" ]]; then
  echo "Torch phrase checkpoint not found: $COMMAND_CLASSIFIER_CHECKPOINT" >&2
  exit 1
fi

if [[ "$COMMAND_BACKEND" == "prototype" ]]; then
  echo "Recording mode: COMMAND_BACKEND=prototype (not the official classifier demo)"
else
  echo "Official classifier demo: COMMAND_BACKEND=$COMMAND_BACKEND"
fi

bash scripts/setup_amd_real.sh
bash scripts/start_real_rocm.sh
