#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

test -x "$BIGYM_PYTHON" || fail "BiGym ROCm Python is missing: $BIGYM_PYTHON"
test -d "$BIGYM_DIR/.git" || fail "run bootstrap_bigym_source.sh first"
test -f "$SHELL_DIR/scene-shell-profile.json" || fail "run download_shell.sh first"

MODE=${1:-smoke}
HUMAN_VISUAL_REVIEW=${HUMAN_VISUAL_REVIEW:-pending}
case "$MODE" in
  smoke) N_EPISODES=${N_EPISODES:-3} ;;
  formal) N_EPISODES=${N_EPISODES:-32} ;;
  custom) test -n "${N_EPISODES:-}" || fail "custom mode requires N_EPISODES" ;;
  *) fail "mode must be smoke, formal or custom" ;;
esac
case "$N_EPISODES" in
  ''|*[!0-9]*|0) fail "N_EPISODES must be a positive integer" ;;
esac

RUN_NAME=${RUN_NAME:-$MODE-full-v2}
RESUME=${RESUME:-1}
case "$RESUME" in
  0|1) ;;
  *) fail "RESUME must be 0 or 1" ;;
esac
RESTART_INTERRUPTED=${RESTART_INTERRUPTED:-1}
case "$RESTART_INTERRUPTED" in
  0|1) ;;
  *) fail "RESTART_INTERRUPTED must be 0 or 1" ;;
esac

OUTPUT_DIR="$RESULTS_ROOT/$RUN_NAME"
mkdir -p "$OUTPUT_DIR" "$RUNTIME_EVIDENCE_DIR"

curl --fail --silent "$INFERENCE_BASE_URL/health" > "$RUNTIME_EVIDENCE_DIR/inference-health.json"
export ROCR_VISIBLE_DEVICES=$SIM_GPU
export HIP_VISIBLE_DEVICES=$SIM_GPU
export MUJOCO_GL=${MUJOCO_GL:-egl}
export PYOPENGL_PLATFORM=${PYOPENGL_PLATFORM:-egl}
export PYTHONPATH="$BIGYM_DIR${PYTHONPATH:+:$PYTHONPATH}"
export TORCH_EXTENSIONS_DIR=${TORCH_EXTENSIONS_DIR:-$AMD_EVAL_ROOT/cache/torch-extensions-gsplat}
export GSPLAT_PREBUILT_DIR=${GSPLAT_PREBUILT_DIR:-}

RESUME_ARGS=()
if test "$RESUME" = 1; then
  RESUME_ARGS+=(--resume)
fi
if test "$RESUME" = 1 && test "$RESTART_INTERRUPTED" = 1; then
  RESUME_ARGS+=(--restart-interrupted)
fi

"$BIGYM_PYTHON" "$EVAL_DIR/src/eval_bigym_3dgs.py" \
  --bigym-root "$BIGYM_DIR" \
  --task DishwasherUnloadCutleryLong \
  --base-url "$INFERENCE_BASE_URL" \
  --visual-shell-profile "$SHELL_DIR/scene-shell-profile.json" \
  --output-dir "$OUTPUT_DIR" \
  --n-episodes "$N_EPISODES" \
  --seed0 0 \
  --tag "amd-$INFERENCE_PROVIDER-$RUN_NAME" \
  --run-id "$RUN_NAME" \
  "${RESUME_ARGS[@]}"

"$BIGYM_PYTHON" "$EVAL_DIR/src/validate_recording.py" \
  --task-dir "$OUTPUT_DIR/dishwasher_unload_cutlery_long" \
  --expected-episodes "$N_EPISODES" \
  --output "$OUTPUT_DIR/recording-validation.json"

python3 "$EVAL_DIR/src/summarize_results.py" \
  --results "$OUTPUT_DIR/dishwasher_unload_cutlery_long/results.json" \
  --recording-validation "$OUTPUT_DIR/recording-validation.json" \
  --output "$OUTPUT_DIR/evaluation-summary.json" \
  --expected-episodes "$N_EPISODES" \
  --human-visual-review "$HUMAN_VISUAL_REVIEW"

rocm-smi --showmeminfo vram --showuse > "$RUNTIME_EVIDENCE_DIR/rocm-smi-after-$RUN_NAME.txt"
printf 'BIGYM_EVAL_COMPLETE mode=%s run=%s episodes=%s output=%s\n' \
  "$MODE" "$RUN_NAME" "$N_EPISODES" "$OUTPUT_DIR"
