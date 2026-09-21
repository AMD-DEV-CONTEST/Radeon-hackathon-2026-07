#!/usr/bin/env zsh
set -euo pipefail

repo_root="${0:A:h:h}"
cd "$repo_root"

source third_party/RLinf/.venv-libero/bin/activate
export PYTHONPATH="$repo_root/third_party/RLinf:${PYTHONPATH:-}"
export LIBERO_CONFIG_PATH="$repo_root/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl

comparison="reports/libero_long_exp/qvgm_tiebreak_states0_9_comparison.json"
if [[ ! -f "$comparison" ]]; then
  print -u2 "missing completed Q-VGM tiebreak comparison: $comparison"
  exit 2
fi
if [[ "$(jq -r '.unique_recommendation_for_10x50 // empty' "$comparison")" != "" ]]; then
  print -u2 "comparison has a unique winner; tied-checkpoint launcher is not applicable"
  exit 2
fi
labels=(${(f)"$(jq -r '.highest_point_estimate_labels[]' "$comparison")"})
if [[ "${(j:,:)labels}" != "step000500,step001000" ]]; then
  print -u2 "unexpected tied checkpoints: ${(j:,:)labels}"
  exit 2
fi

policy_root="checkpoints/qvgm_policy/libero_long_orientation_fixed_v2_residual_velocity_v1"
typeset -A model gate_0_4 gate_5_9 formal
model[step000500]="$policy_root/checkpoint-000500/pretrained_model"
model[step001000]="$policy_root/checkpoint-001000/pretrained_model"
gate_0_4[step000500]="outputs/libero_long/orientation_fixed_v2_qvgm_step000500_5states"
gate_0_4[step001000]="outputs/libero_long/orientation_fixed_v2_qvgm_step001000_5states"
gate_5_9[step000500]="outputs/libero_long/orientation_fixed_v2_tiebreak_qvgm_step000500_states5_9"
gate_5_9[step001000]="outputs/libero_long/orientation_fixed_v2_tiebreak_qvgm_step001000_states5_9"
formal[step000500]="outputs/libero_long/orientation_fixed_v2_qvgm_step000500_states10_49"
formal[step001000]="outputs/libero_long/orientation_fixed_v2_qvgm_step001000_states10_49"

run_candidate() {
  local label="$1"
  local gpu="$2"
  shift 2
  export CUDA_VISIBLE_DEVICES="$gpu"
  mkdir -p "${formal[$label]}"
  for task in "$@"; do
    python scripts/run_smolvla_libero_sweep.py \
      --task-suite libero_10 --task-id "$task" \
      --states 10-49 --seeds 2001 --max-steps 600 --action-steps 5 \
      --model-path "${model[$label]}" \
      --output-dir "${formal[$label]}/task_$task"
  done
  python scripts/summarize_libero_suite_results.py \
    --input-dir "${gate_0_4[$label]}" \
    --input-dir "${gate_5_9[$label]}" \
    --input-dir "${formal[$label]}" \
    --method qvgm --seed 2001 \
    --expected-tasks 0-9 --expected-states 0-49 \
    --output-json "reports/libero_long_exp/qvgm_${label}_suite.json" \
    --output-md "reports/libero_long_exp/qvgm_${label}_suite.md"
}

run_candidate step000500 0 0 1 2 3 4 5 6 7 8 9 &
gpu0_pid=$!
run_candidate step001000 1 0 1 2 3 4 5 6 7 8 9 &
gpu1_pid=$!
wait "$gpu0_pid"
wait "$gpu1_pid"

print "completed both tied Q-VGM 10x50 evaluations"
