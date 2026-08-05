#!/usr/bin/env zsh
set -euo pipefail

repo_root="${0:A:h:h}"
cd "$repo_root"

source third_party/RLinf/.venv-libero/bin/activate
export PYTHONPATH="$repo_root/third_party/RLinf:${PYTHONPATH:-}"

input_root="outputs/libero_long/orientation_fixed_v2_q_guidance_a005_n005_s10_lr002_d005_50states"
base_root="outputs/libero_long/orientation_fixed_v2_final_5trials"
report_root="reports/libero_long_exp"

count=$(find "$input_root" -name closed_loop_metrics.json 2>/dev/null | wc -l | tr -d ' ')
if [[ "$count" != 500 ]]; then
  print -u2 "incomplete Q-guidance sweep: $count/500"
  exit 2
fi

mkdir -p "$report_root"
python scripts/summarize_libero_suite_results.py \
  --input-dir "$input_root" \
  --method guidance --seed 2001 \
  --expected-tasks 0-9 --expected-states 0-49 \
  --output-json "$report_root/q_guidance_suite.json" \
  --output-md "$report_root/q_guidance_suite.md"

python scripts/summarize_libero_suite_paired.py \
  --base-dir "$base_root" \
  --candidate-dir "$input_root" \
  --method guidance --seed 2001 \
  --expected-tasks 0-9 --expected-states 0-4 \
  --output-json "$report_root/q_guidance_paired_states0_4.json" \
  --output-md "$report_root/q_guidance_paired_states0_4.md"

print "completed Q-guidance suite and paired reports"
