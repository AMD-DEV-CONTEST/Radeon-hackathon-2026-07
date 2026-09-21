#!/usr/bin/env bash
set -euo pipefail

ROOT=/workspace/QVGM
PY="$ROOT/.venv-rocm/bin/python"
RUN_LOG_DIR="$ROOT/outputs/logs"
export TOKENIZERS_PARALLELISM=false

mkdir -p "$RUN_LOG_DIR"
cd "$ROOT"

run_one() {
  local episodes="$1"
  local config="configs/experiments/lerobot_stove_${episodes}ep_30k_sft.yaml"
  local log="$RUN_LOG_DIR/sft_lerobot_stove_${episodes}ep_30k.log"

  echo "[$(date -Is)] starting ${episodes}-episode, 30000-step SFT: $config"
  "$PY" scripts/train_smolvla_libero_task0.py --config "$config" 2>&1 | tee "$log"
  echo "[$(date -Is)] completed ${episodes}-episode, 30000-step SFT"
}

run_one 10
run_one 20
