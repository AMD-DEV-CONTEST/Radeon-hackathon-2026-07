#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

requests="${BENCH_REQUESTS:-20}"
concurrency="${BENCH_CONCURRENCY:-1}"
max_tokens="${BENCH_MAX_TOKENS:-192}"
gpu_seconds="${GPU_RECORD_SECONDS:-180}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
gpu_log="artifacts/amd-smi-baseline-${stamp}.log"
gpu_stdout="artifacts/amd-smi-baseline-${stamp}.stdout"
gpu_summary="artifacts/amd-smi-baseline-${stamp}.json"
run_log="artifacts/baseline-run-${stamp}.log"

mkdir -p artifacts benchmarks/reports

bash scripts/verify_local_only.sh | tee -a "$run_log"

bash scripts/record_gpu_metrics.sh "$gpu_seconds" 1 "$gpu_log" >"$gpu_stdout" 2>&1 &
gpu_recorder_pid=$!

benchmark_status=0
python3 benchmarks/baseline.py \
  --requests "$requests" \
  --concurrency "$concurrency" \
  --max-tokens "$max_tokens" \
  2>&1 | tee -a "$run_log" || benchmark_status=$?

wait "$gpu_recorder_pid" || gpu_status=$?
gpu_status="${gpu_status:-0}"

printf 'benchmark_exit_code=%s\n' "$benchmark_status" | tee -a "$run_log"
printf 'gpu_recorder_exit_code=%s\n' "$gpu_status" | tee -a "$run_log"
printf 'gpu_log=%s\n' "$gpu_log" | tee -a "$run_log"
printf 'gpu_stdout=%s\n' "$gpu_stdout" | tee -a "$run_log"

if (( benchmark_status != 0 || gpu_status != 0 )); then
  echo "FAILURE: baseline or GPU recording failed." | tee -a "$run_log"
  echo "NEXT: inspect this run log, the vLLM log, and the environment fingerprint." \
    | tee -a "$run_log"
  exit 1
fi

python3 scripts/summarize_gpu_metrics.py "$gpu_log" --output "$gpu_summary" \
  | tee -a "$run_log"

echo "Baseline and GPU recording completed." | tee -a "$run_log"
