#!/usr/bin/env zsh
set -euo pipefail

repo_root="${0:A:h:h}"
cd "$repo_root"

source third_party/RLinf/.venv-libero/bin/activate
export PYTHONPATH="$repo_root/third_party/RLinf:${PYTHONPATH:-}"
export LIBERO_CONFIG_PATH="$repo_root/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl

base_0_4="outputs/libero_long/orientation_fixed_v2_final_5trials"
base_5_9="outputs/libero_long/orientation_fixed_v2_tiebreak_sft_states5_9"
policy_root="checkpoints/qvgm_policy/libero_long_orientation_fixed_v2_residual_velocity_v1"
report_root="reports/libero_long_exp"

typeset -A gate_0_4 gate_5_9 model_path
gate_0_4[step000500]="outputs/libero_long/orientation_fixed_v2_qvgm_step000500_5states"
gate_0_4[step001000]="outputs/libero_long/orientation_fixed_v2_qvgm_step001000_5states"
gate_0_4[final]="outputs/libero_long/orientation_fixed_v2_qvgm_final_5states"
gate_5_9[step000500]="outputs/libero_long/orientation_fixed_v2_tiebreak_qvgm_step000500_states5_9"
gate_5_9[step001000]="outputs/libero_long/orientation_fixed_v2_tiebreak_qvgm_step001000_states5_9"
gate_5_9[final]="outputs/libero_long/orientation_fixed_v2_tiebreak_qvgm_final_states5_9"
model_path[step000500]="$policy_root/checkpoint-000500/pretrained_model"
model_path[step001000]="$policy_root/checkpoint-001000/pretrained_model"
model_path[final]="$policy_root/checkpoint-final/pretrained_model"

metric_count() {
  find "$1" -name closed_loop_metrics.json 2>/dev/null | wc -l | tr -d ' '
}

for label in step000500 final; do
  count=$(metric_count "${gate_5_9[$label]}")
  if [[ "$count" != 50 ]]; then
    print -u2 "incomplete $label states 5-9 gate: $count/50"
    exit 2
  fi
done

mkdir -p "$report_root"
for label in step000500 final; do
  python scripts/summarize_libero_suite_paired.py \
    --base-dir "$base_5_9" \
    --candidate-dir "${gate_5_9[$label]}" \
    --method qvgm --seed 2001 \
    --expected-tasks 0-9 --expected-states 5-9 \
    --output-json "$report_root/qvgm_${label}_tiebreak_states5_9.json" \
    --output-md "$report_root/qvgm_${label}_tiebreak_states5_9.md"
done

for label in step000500 step001000 final; do
  python scripts/summarize_libero_suite_paired.py \
    --base-dir "$base_0_4" --base-dir "$base_5_9" \
    --candidate-dir "${gate_0_4[$label]}" \
    --candidate-dir "${gate_5_9[$label]}" \
    --method qvgm --seed 2001 \
    --expected-tasks 0-9 --expected-states 0-9 \
    --output-json "$report_root/qvgm_${label}_gate_states0_9.json" \
    --output-md "$report_root/qvgm_${label}_gate_states0_9.md"
done

python scripts/compare_qvgm_gates.py \
  --expected-count 3 \
  --gate "step000500=$report_root/qvgm_step000500_gate_states0_9.json" \
  --gate "step001000=$report_root/qvgm_step001000_gate_states0_9.json" \
  --gate "final=$report_root/qvgm_final_gate_states0_9.json" \
  --output-json "$report_root/qvgm_tiebreak_states0_9_comparison.json" \
  --output-md "$report_root/qvgm_tiebreak_states0_9_comparison.md"

selected=$(jq -r '.unique_recommendation_for_10x50 // empty' \
  "$report_root/qvgm_tiebreak_states0_9_comparison.json")
if [[ -z "$selected" ]]; then
  print -u2 "no unique gate winner; formal evaluation was not launched"
  exit 3
fi

formal_root="outputs/libero_long/orientation_fixed_v2_qvgm_${selected}_states10_49"
mkdir -p "$formal_root"

run_tasks() {
  local gpu="$1"
  shift
  export CUDA_VISIBLE_DEVICES="$gpu"
  for task in "$@"; do
    python scripts/run_smolvla_libero_sweep.py \
      --task-suite libero_10 --task-id "$task" \
      --states 10-49 --seeds 2001 --max-steps 600 --action-steps 5 \
      --model-path "${model_path[$selected]}" \
      --output-dir "$formal_root/task_$task"
  done
}

run_tasks 0 0 2 4 6 8 &
gpu0_pid=$!
run_tasks 1 1 3 5 7 9 &
gpu1_pid=$!
wait "$gpu0_pid"
wait "$gpu1_pid"

python scripts/summarize_libero_suite_results.py \
  --input-dir "${gate_0_4[$selected]}" \
  --input-dir "${gate_5_9[$selected]}" \
  --input-dir "$formal_root" \
  --method qvgm --seed 2001 \
  --expected-tasks 0-9 --expected-states 0-49 \
  --output-json "$report_root/qvgm_${selected}_suite.json" \
  --output-md "$report_root/qvgm_${selected}_suite.md"

print "completed selected Q-VGM formal evaluation: $selected"
