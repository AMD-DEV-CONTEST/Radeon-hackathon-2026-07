#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PYTHON=${PYTHON:-python3}
WORK_ROOT=${WORK_ROOT:-"$REPO_ROOT/.repro/kitchen"}
SOURCE_ARCHIVE=${SOURCE_ARCHIVE:?set SOURCE_ARCHIVE to the authorized DL3DV zip}
SOURCE_REPORT=${SOURCE_REPORT:?set SOURCE_REPORT to source.json from the downloader}
GSPLAT_DIR=${GSPLAT_DIR:?set GSPLAT_DIR to pinned gsplat checkout}
BIGYM_DIR=${BIGYM_DIR:?set BIGYM_DIR to the patched BiGym checkout}
TRAIN_STEPS=${TRAIN_STEPS:-30000}
SOURCE_SCREENING_REPORT=${SOURCE_SCREENING_REPORT:-}
RUN_BIGYM_ACCEPTANCE=${RUN_BIGYM_ACCEPTANCE:-0}

PREPARED="$WORK_ROOT/prepared"
TRAINING="$WORK_ROOT/training"
FULL_ASSETS="$WORK_ROOT/full-assets"
SHELL_ASSETS="$WORK_ROOT/shell-assets"
REPORTS="$WORK_ROOT/reports"
mkdir -p "$PREPARED" "$TRAINING" "$FULL_ASSETS" "$SHELL_ASSETS" "$REPORTS"

test -f "$SOURCE_ARCHIVE"
test -f "$SOURCE_REPORT"
test -f "$GSPLAT_DIR/examples/simple_trainer.py"
test -f "$BIGYM_DIR/d/replay_generation/env_utils.py"

"$PYTHON" -m compileall -q "$REPO_ROOT/reconstruction/src"
"$PYTHON" "$REPO_ROOT/reconstruction/src/prepare_dl3dv_scene.py" \
  --archive "$SOURCE_ARCHIVE" \
  --output "$PREPARED" \
  --report "$REPORTS/dataset-preparation.json"

DATASET="$PREPARED/dataset"
run_candidate() {
  local candidate=$1
  local result="$TRAINING/$candidate-$TRAIN_STEPS"
  if compgen -G "$result/stats/val_step*.json" >/dev/null \
    && compgen -G "$result/ckpts/ckpt_*_rank0.pt" >/dev/null; then
    printf 'Reusing completed candidate %s\n' "$result"
    return
  fi
  "$PYTHON" "$GSPLAT_DIR/examples/simple_trainer.py" "$candidate" \
    --data-dir "$DATASET" \
    --data-factor 1 \
    --result-dir "$result" \
    --test-every 8 \
    --max-steps "$TRAIN_STEPS" \
    --eval-steps "$TRAIN_STEPS" \
    --save-steps "$TRAIN_STEPS" \
    --sh-degree 3 \
    --antialiased \
    --lpips-net vgg \
    --disable-viewer \
    >"$REPORTS/gsplat-$candidate-$TRAIN_STEPS.log" 2>&1
}

run_candidate default
run_candidate mcmc

SELECTION="$REPORTS/candidate-selection.json"
"$PYTHON" "$REPO_ROOT/reconstruction/src/select_training_candidate.py" \
  --training-root "$TRAINING" \
  --steps "$TRAIN_STEPS" \
  --output "$SELECTION"

readarray -t SELECTED < <(
  "$PYTHON" -c \
    'import json,sys; x=json.load(open(sys.argv[1])); s=x["selected"]; print(s["name"]); print(s["checkpoint"]); print(s["metrics_path"])' \
    "$SELECTION"
)
SELECTED_NAME=${SELECTED[0]}
SELECTED_CHECKPOINT=${SELECTED[1]}
SELECTED_METRICS=${SELECTED[2]}

PYTHONPATH="$GSPLAT_DIR/examples${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" "$REPO_ROOT/reconstruction/src/export_discoverse_background.py" \
  --dataset "$DATASET" \
  --gsplat "$GSPLAT_DIR" \
  --checkpoint "$SELECTED_CHECKPOINT" \
  --metrics "$SELECTED_METRICS" \
  --output "$FULL_ASSETS" \
  --candidate "$SELECTED_NAME" \
  --steps "$TRAIN_STEPS" \
  --data-factor 1 \
  --test-every 8 \
  --trajectory-frames 540 \
  >"$REPORTS/gaussian-export.json"

"$PYTHON" "$REPO_ROOT/reconstruction/src/measure_bigym_workspace.py" \
  --bigym-dir "$BIGYM_DIR" \
  --task DishwasherUnloadCutleryLong \
  --output "$REPORTS/workspace-obb.json"

SCREENING_ARGS=()
if test -n "$SOURCE_SCREENING_REPORT"; then
  test -f "$SOURCE_SCREENING_REPORT"
  SCREENING_ARGS=(--source-screening-report "$SOURCE_SCREENING_REPORT")
fi
"$PYTHON" "$REPO_ROOT/reconstruction/src/export_scene_shell.py" \
  --input "$FULL_ASSETS/gaussians.ply" \
  --camera-path "$FULL_ASSETS/camera-path.json" \
  --output "$SHELL_ASSETS" \
  --source-report "$SOURCE_REPORT" \
  --workspace-obb "$REPORTS/workspace-obb.json" \
  --workspace-margin 0.30 \
  --camera-height 1.55 \
  "${SCREENING_ARGS[@]}" \
  >"$REPORTS/scene-shell-export.json"

"$PYTHON" "$REPO_ROOT/reconstruction/src/verify_shell_export.py" \
  "$SHELL_ASSETS" --allow-pending-visual-review

if test "$RUN_BIGYM_ACCEPTANCE" = 1; then
  "$PYTHON" "$REPO_ROOT/reconstruction/src/validate_bigym_visual_shell.py" \
    --bigym-dir "$BIGYM_DIR" \
    --profile "$SHELL_ASSETS/scene-shell-profile.json" \
    --output "$WORK_ROOT/bigym-acceptance" \
    --task DishwasherUnloadCutleryLong \
    --frames 300
fi

printf 'Reconstruction complete: %s\n' "$SHELL_ASSETS"
