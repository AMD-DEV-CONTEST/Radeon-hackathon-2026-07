#!/usr/bin/env bash
# Generate Env-A static pick-and-place dataset on AMD ROCm.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-/workspace/rdna/bin/python}"
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-/workspace/cache/huggingface/lerobot}"
export HF_HOME="${HF_HOME:-/workspace/cache/huggingface}"
mkdir -p "$HF_LEROBOT_HOME" "$ROOT/output/smoke" "$ROOT/artifacts"

cd "$ROOT"

MODE="${1:-smoke}"

if [[ "$MODE" == "smoke" ]]; then
  echo "[run] smoke: 2 episodes"
  "$PY" scripts/gen_pick_place.py \
    --n-episodes 2 \
    --seed 42 \
    --scene rustic_kitchen \
    --anchor floor_origin \
    --camera-layout up_wrist \
    --repo-id local/franka-kitchen-fruit-place-smoke \
    --output-dir "$ROOT/output" \
    --smoke-dump-pngs "$ROOT/output/smoke/pngs"
elif [[ "$MODE" == "full" ]]; then
  echo "[run] full Env-A: 120 success episodes"
  "$PY" scripts/gen_pick_place.py \
    --n-episodes 120 \
    --seed 42 \
    --scene rustic_kitchen \
    --anchor floor_origin \
    --camera-layout up_wrist \
    --repo-id local/franka-kitchen-fruit-place-120ep \
    --output-dir "$ROOT/output"
else
  echo "Usage: $0 [smoke|full]"
  exit 1
fi
