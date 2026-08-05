#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/QVGM"
TRAIN_PID_FILE="$ROOT/outputs/logs/task7_native20d_qvgm1000_train.pid"
TRAIN_LOG="$ROOT/outputs/logs/task7_native20d_qvgm1000_train.log"
OUTPUT="$ROOT/checkpoints/qvgm_policy/task7_native20d20k_q3_residual_1000_v1"
MODEL="$OUTPUT/checkpoint-final/pretrained_model"
EVAL="$ROOT/outputs/task7_q3_native20d20k/qvgm_residual_1000_seed2001"
EVAL_LOG="$ROOT/outputs/logs/task7_native20d_qvgm1000_eval.log"

export TOKENIZERS_PARALLELISM=false
export SMOLVLA_ATTENTION_BACKEND=sdpa
export PYTHONPATH="/workspace/LIBERO-sim${PYTHONPATH:+:$PYTHONPATH}"
export LIBERO_CONFIG_PATH="$ROOT/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl

train_pid="$(cat "$TRAIN_PID_FILE")"
echo "$(date -u +%FT%TZ) waiting for 20D QVGM step-1000 PID $train_pid"
while kill -0 "$train_pid" 2>/dev/null; do
  sleep 30
done

for required in \
  "$MODEL/model.safetensors" \
  "$MODEL/config.json" \
  "$OUTPUT/checkpoint-final/trainer_state.pt" \
  "$OUTPUT/metrics.json"; do
  [[ -s "$required" ]] || {
    echo "missing step-1000 training artifact: $required" >&2
    exit 1
  }
done

"$ROOT/.venv-rocm/bin/python" - "$OUTPUT" <<'PY'
import json
import pathlib
import sys
import torch

root = pathlib.Path(sys.argv[1])
metrics = json.loads((root / "metrics.json").read_text())
state = torch.load(
    root / "checkpoint-final" / "trainer_state.pt",
    map_location="cpu",
    weights_only=False,
)
assert metrics["steps"] == 1000, metrics["steps"]
assert metrics["start_step"] == 500, metrics["start_step"]
assert state["step"] == 1000, state["step"]
print("validated resumed QVGM checkpoint at step 1000", flush=True)
PY

echo "$(date -u +%FT%TZ) starting paired 50-state QVGM-1000 evaluation"
cd "$ROOT"
"$ROOT/.venv-rocm/bin/python" scripts/run_smolvla_libero_sweep.py \
  --states 0-49 \
  --seeds 2001 \
  --task-id 7 \
  --task-suite libero_spatial \
  --max-steps 240 \
  --action-steps 5 \
  --model-path "$MODEL" \
  --output-dir "$EVAL" \
  >>"$EVAL_LOG" 2>&1

[[ -s "$EVAL/summary.json" ]] || {
  echo "missing QVGM-1000 evaluation summary" >&2
  exit 1
}
echo "$(date -u +%FT%TZ) 20D QVGM step-1000 evaluation complete"
