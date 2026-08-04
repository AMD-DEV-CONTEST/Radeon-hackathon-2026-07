#!/usr/bin/env bash
set -Eeuo pipefail
set -C

usage() {
  echo "Usage: $0 --run-prefix PREFIX --run A|B|C|D|E|all --expected-commit FULL_SHA --output-root NEW_DIRECTORY --model-file GGUF --llama-server BINARY [--model-alias NAME] [--model-port PORT] [--context-size TOKENS] [--dry-run]" >&2
}

run_prefix=""
run_selection="all"
expected_commit=""
output_root=""
model_file=""
llama_server=""
model_alias="qwen3.6-35b-a3b-q6k"
model_port="8000"
context_size="16384"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --run-prefix|--run|--expected-commit|--output-root|--model-file|--llama-server|--model-alias|--model-port|--context-size)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      case "$1" in
        --run-prefix) run_prefix="${2:-}" ;;
        --run) run_selection="${2:-}" ;;
        --expected-commit) expected_commit="${2:-}" ;;
        --output-root) output_root="${2:-}" ;;
        --model-file) model_file="${2:-}" ;;
        --llama-server) llama_server="${2:-}" ;;
        --model-alias) model_alias="${2:-}" ;;
        --model-port) model_port="${2:-}" ;;
        --context-size) context_size="${2:-}" ;;
      esac
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ ! "${run_prefix}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,45}$ ]]; then
  echo "Run prefix must be 1-46 evidence-safe characters" >&2
  exit 3
fi
case "${run_selection}" in
  A|B|C|D|E|all) ;;
  *)
    echo "--run must be A, B, C, D, E, or all" >&2
    exit 3
    ;;
esac
if [[ ! "${expected_commit}" =~ ^[0-9a-f]{40,64}$ ]]; then
  echo "--expected-commit must be a full lowercase Git object ID" >&2
  exit 3
fi
if [[ -z "${output_root}" || -z "${model_file}" || -z "${llama_server}" ]]; then
  usage
  exit 2
fi
if [[ ! "${model_port}" =~ ^[1-9][0-9]{0,4}$ ]] || (( model_port > 65535 )); then
  echo "--model-port must be between 1 and 65535" >&2
  exit 3
fi
if [[ ! "${model_alias}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]; then
  echo "--model-alias has an invalid evidence format" >&2
  exit 3
fi
if [[ ! "${context_size}" =~ ^[1-9][0-9]{0,8}$ ]]; then
  echo "--context-size must be a positive integer" >&2
  exit 3
fi
for supplied_path in "${output_root}" "${model_file}" "${llama_server}"; do
  if [[ "${supplied_path}" == *$'\n'* || "${supplied_path}" == *$'\r'* ]]; then
    echo "Matrix paths must not contain CR or LF characters" >&2
    exit 3
  fi
done

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
repository_root="$(git -C "${project_dir}" rev-parse --show-toplevel)"
project_prefix="$(git -C "${project_dir}" rev-parse --show-prefix)"
project_prefix="${project_prefix%/}"
if [[ -z "${project_prefix}" ]]; then
  echo "The matrix runner must execute from a repository subdirectory" >&2
  exit 3
fi

for required_command in git sha256sum; do
  if ! command -v "${required_command}" >/dev/null 2>&1; then
    echo "Required command not found: ${required_command}" >&2
    exit 4
  fi
done
python_bin="${PYTHON_BIN:-python3}"
if [[ ! -f "${model_file}" || ! -x "${llama_server}" ]]; then
  echo "The pinned model file and executable llama-server are required" >&2
  exit 3
fi
model_file="$(cd -- "$(dirname -- "${model_file}")" && pwd -P)/$(basename -- "${model_file}")"
llama_server="$(cd -- "$(dirname -- "${llama_server}")" && pwd -P)/$(basename -- "${llama_server}")"

output_parent="$(dirname -- "${output_root}")"
if [[ ! -d "${output_parent}" ]]; then
  echo "Output-root parent does not exist: ${output_parent}" >&2
  exit 3
fi
output_parent="$(cd -- "${output_parent}" && pwd -P)"
output_root="${output_parent}/$(basename -- "${output_root}")"
if [[ -e "${output_root}" || -L "${output_root}" ]]; then
  echo "Refusing to reuse matrix output root: ${output_root}" >&2
  exit 3
fi
for resolved_path in "${output_root}" "${model_file}" "${llama_server}"; do
  if [[ "${resolved_path}" == *$'\n'* || "${resolved_path}" == *$'\r'* ]]; then
    echo "Resolved matrix paths must not contain CR or LF characters" >&2
    exit 3
  fi
done

results_root="$(cd -- "${project_dir}/evaluation/results" && pwd -P)"
case "${output_root}/" in
  "${repository_root}/"*)
    case "${output_root}/" in
      "${results_root}/"*) ;;
      *)
        echo "Repository-local outputs must stay under evaluation/results" >&2
        exit 3
        ;;
    esac
    ;;
esac

assert_c2_binding() {
  local actual_commit project_status
  actual_commit="$(git -C "${project_dir}" rev-parse --verify HEAD)"
  if [[ "${actual_commit}" != "${expected_commit}" ]]; then
    echo "C2 binding failed: HEAD ${actual_commit} != ${expected_commit}" >&2
    return 1
  fi
  project_status="$(
    git -C "${project_dir}" status --porcelain=v1 --untracked-files=all -- .
  )"
  if [[ -n "${project_status}" ]]; then
    echo "C2 binding failed: RadeonStay source is not clean" >&2
    return 1
  fi
}

assert_c2_binding
c2_project_tree="$(git -C "${project_dir}" rev-parse "HEAD:${project_prefix}")"
pinned_model_sha256="$(sha256sum -- "${model_file}" | awk '{print $1}')"
pinned_llama_sha256="$(sha256sum -- "${llama_server}" | awk '{print $1}')"

assert_artifact_binding() {
  local current_model_sha256 current_llama_sha256
  current_model_sha256="$(sha256sum -- "${model_file}" | awk '{print $1}')"
  current_llama_sha256="$(sha256sum -- "${llama_server}" | awk '{print $1}')"
  if [[ "${current_model_sha256}" != "${pinned_model_sha256}" \
        || "${current_llama_sha256}" != "${pinned_llama_sha256}" ]]; then
    echo "Pinned model or llama-server changed during the matrix" >&2
    return 1
  fi
}

configure_experiment() {
  local experiment="$1"
  # A/B is the formal thinking-only pair. C, D, and E then change flash
  # attention, batch/ubatch, and parallelism as independent follow-up steps.
  case "${experiment}" in
    A) thinking="on";  flash_attn="off"; batch_size="256"; ubatch_size="64";  parallel_slots="1" ;;
    B) thinking="off"; flash_attn="off"; batch_size="256"; ubatch_size="64";  parallel_slots="1" ;;
    C) thinking="off"; flash_attn="on";  batch_size="256"; ubatch_size="64";  parallel_slots="1" ;;
    D) thinking="off"; flash_attn="on";  batch_size="512"; ubatch_size="128"; parallel_slots="1" ;;
    E) thinking="off"; flash_attn="on";  batch_size="512"; ubatch_size="128"; parallel_slots="4" ;;
    *) return 2 ;;
  esac
}

if [[ "${run_selection}" == "all" ]]; then
  selected_experiments=(A B C D E)
else
  selected_experiments=("${run_selection}")
fi

print_dry_run() {
  local experiment="$1"
  configure_experiment "${experiment}"
  echo "dry_run=true"
  echo "experiment=${experiment}"
  echo "run_id=${run_prefix}-${experiment}"
  echo "output_dir=${output_root}/${experiment}"
  echo "c2_expected_commit=${expected_commit}"
  echo "c2_project_tree=${c2_project_tree}"
  echo "model_alias=${model_alias} context_size=${context_size}"
  echo "model_sha256=${pinned_model_sha256} llama_server_sha256=${pinned_llama_sha256}"
  echo "thinking=${thinking} flash_attn=${flash_attn} batch=${batch_size} ubatch=${ubatch_size} parallel=${parallel_slots}"
  echo "stages=serve_model,monitor_rocm,retrieval,agent_quality,benchmark,controlled_child_shutdown,collect_rocm_evidence"
  if [[ "${run_selection}" == "all" ]]; then
    echo "formal_comparison=A-vs-B-thinking-only"
  else
    echo "formal_comparison=not_scheduled_for_single_run"
  fi
}

if (( dry_run == 1 )); then
  for experiment in "${selected_experiments[@]}"; do
    print_dry_run "${experiment}"
  done
  exit 0
fi

for required_command in curl grep rocm-smi rocminfo; do
  if ! command -v "${required_command}" >/dev/null 2>&1; then
    echo "Required live-run command not found: ${required_command}" >&2
    exit 4
  fi
done
if ! command -v "${python_bin}" >/dev/null 2>&1; then
  echo "Python executable not found: ${python_bin}" >&2
  exit 4
fi

mkdir -m 0700 -- "${output_root}"
matrix_status_file="${output_root}/matrix-status.log"
{
  echo "matrix_started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "run_prefix=${run_prefix}"
  echo "expected_commit=${expected_commit}"
  echo "project_tree=${c2_project_tree}"
  echo "model_sha256=${pinned_model_sha256}"
  echo "llama_server_sha256=${pinned_llama_sha256}"
} > "${matrix_status_file}"

run_experiment() (
  set -Eeuo pipefail
  set -C
  local experiment="$1"
  local run_id="${run_prefix}-${experiment}"
  local run_dir="${output_root}/${experiment}"
  local server_log="${run_dir}/llama-server.log"
  local monitor_log="${run_dir}/rocm-monitor.log"
  local stop_file="${run_dir}/monitor.stop"
  local retrieval_file="${run_dir}/retrieval.json"
  local quality_file="${run_dir}/agent-quality.json"
  local benchmark_file="${run_dir}/agent-benchmark.json"
  local evidence_dir="${run_dir}/evidence"
  local status_file="${run_dir}/orchestration-status.log"
  local manifest_file="${run_dir}/experiment-manifest.txt"
  local server_pid=""
  local monitor_pid=""
  local server_active=0
  local monitor_active=0
  local run_complete=0
  local current_stage="preflight"

  configure_experiment "${experiment}"
  mkdir -m 0700 -- "${run_dir}"
  {
    echo "schema_version=1"
    echo "experiment=${experiment}"
    echo "run_id=${run_id}"
    echo "c2_binding_status=verified"
    echo "commit=${expected_commit}"
    echo "project_tree=${c2_project_tree}"
    echo "model_file=${model_file}"
    echo "model_sha256=${pinned_model_sha256}"
    echo "llama_server=${llama_server}"
    echo "llama_server_sha256=${pinned_llama_sha256}"
    echo "model_alias=${model_alias}"
    echo "context_size=${context_size}"
    echo "thinking=${thinking}"
    echo "flash_attn=${flash_attn}"
    echo "batch_size=${batch_size}"
    echo "ubatch_size=${ubatch_size}"
    echo "parallel_slots=${parallel_slots}"
  } > "${manifest_file}"
  echo "started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) stage=preflight status=started" > "${status_file}"

  record_stage() {
    echo "at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) stage=${current_stage} status=$1" >> "${status_file}"
  }

  stop_monitor_child() {
    local monitor_status=0
    if (( monitor_active == 0 )); then
      return 0
    fi
    if kill -0 "${monitor_pid}" 2>/dev/null && [[ ! -e "${stop_file}" ]]; then
      : > "${stop_file}"
    fi
    if wait "${monitor_pid}"; then
      monitor_status=0
    else
      monitor_status=$?
    fi
    monitor_active=0
    if (( monitor_status != 0 )); then
      echo "Monitor child exited with status ${monitor_status}" >&2
      return 1
    fi
  }

  stop_server_child() {
    local server_status=0
    if (( server_active == 0 )); then
      return 0
    fi
    if kill -0 "${server_pid}" 2>/dev/null; then
      kill -TERM "${server_pid}"
    fi
    if wait "${server_pid}"; then
      server_status=0
    else
      server_status=$?
    fi
    server_active=0
    if (( server_status != 0 && server_status != 143 )); then
      echo "Model launcher child exited with status ${server_status}" >&2
      return 1
    fi
  }

  finalize_run() {
    local exit_status=$?
    local cleanup_failed=0
    set +e
    stop_monitor_child || cleanup_failed=1
    stop_server_child || cleanup_failed=1
    if (( cleanup_failed != 0 && exit_status == 0 )); then
      exit_status=1
    fi
    if (( run_complete == 1 && exit_status == 0 )); then
      echo "completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) status=complete" >> "${status_file}"
    else
      echo "completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) status=failed stage=${current_stage} exit_code=${exit_status}" >> "${status_file}"
      if (( exit_status == 0 )); then
        exit_status=1
      fi
    fi
    trap - EXIT
    exit "${exit_status}"
  }
  trap finalize_run EXIT

  assert_c2_binding
  assert_artifact_binding
  if curl --silent --show-error --max-time 2 \
      "http://127.0.0.1:${model_port}/v1/models" >/dev/null 2>&1; then
    echo "Refusing to use occupied model port ${model_port}" >&2
    return 1
  fi

  current_stage="serve_model"
  record_stage started
  env \
    LLAMA_SERVER="${llama_server}" \
    MODEL_PATH="${model_file}" \
    MODEL_ALIAS="${model_alias}" \
    MODEL_PORT="${model_port}" \
    CONTEXT_SIZE="${context_size}" \
    EVIDENCE_RUN_ID="${run_id}" \
    FLASH_ATTN="${flash_attn}" \
    PARALLEL_SLOTS="${parallel_slots}" \
    BATCH_SIZE="${batch_size}" \
    UBATCH_SIZE="${ubatch_size}" \
    "${project_dir}/scripts/serve_model.sh" > "${server_log}" 2>&1 &
  server_pid=$!
  server_active=1

  current_stage="model_readiness"
  record_stage started
  model_ready=0
  for ((attempt = 1; attempt <= 120; attempt++)); do
    if ! kill -0 "${server_pid}" 2>/dev/null; then
      echo "Model launcher exited before readiness" >&2
      return 1
    fi
    if curl --fail --silent --show-error --max-time 2 \
        "http://127.0.0.1:${model_port}/v1/models" >/dev/null; then
      model_ready=1
      break
    fi
    sleep 1
  done
  if (( model_ready == 0 )); then
    echo "Model endpoint did not become ready within 120 seconds" >&2
    return 1
  fi
  record_stage complete

  current_stage="monitor_rocm"
  record_stage started
  "${project_dir}/scripts/monitor_rocm.sh" \
    --run-id "${run_id}" \
    --output "${monitor_log}" \
    --interval 1 \
    --samples 7200 \
    --stop-file "${stop_file}" &
  monitor_pid=$!
  monitor_active=1

  current_stage="monitor_readiness"
  record_stage started
  monitor_ready=0
  for ((attempt = 1; attempt <= 10; attempt++)); do
    if ! kill -0 "${monitor_pid}" 2>/dev/null; then
      echo "ROCm monitor exited before its first sample" >&2
      return 1
    fi
    if grep -Fq "sample=1 run_id=${run_id} " "${monitor_log}" 2>/dev/null; then
      monitor_ready=1
      break
    fi
    sleep 1
  done
  if (( monitor_ready == 0 )); then
    echo "ROCm monitor did not produce a first sample within 10 seconds" >&2
    return 1
  fi
  record_stage complete

  thinking_value=0
  if [[ "${thinking}" == "on" ]]; then
    thinking_value=1
  fi
  common_environment=(
    RADEONSTAY_MODEL_BASE_URL="http://127.0.0.1:${model_port}/v1"
    RADEONSTAY_MODEL_NAME="${model_alias}"
    RADEONSTAY_MODEL_ENABLE_THINKING="${thinking_value}"
  )

  current_stage="retrieval"
  record_stage started
  env "${common_environment[@]}" "${python_bin}" \
    "${project_dir}/evaluation/run_retrieval_eval.py" \
    --run-id "${run_id}" \
    --output "${retrieval_file}"
  record_stage complete

  current_stage="agent_quality"
  record_stage started
  env "${common_environment[@]}" "${python_bin}" \
    "${project_dir}/evaluation/run_agent_eval.py" \
    --run-id "${run_id}" \
    --model-file "${model_file}" \
    --llama-server "${llama_server}" \
    --output "${quality_file}"
  record_stage complete

  current_stage="benchmark"
  record_stage started
  env "${common_environment[@]}" "${python_bin}" \
    "${project_dir}/evaluation/benchmark_agent.py" \
    --run-id "${run_id}" \
    --quality-report "${quality_file}" \
    --model-file "${model_file}" \
    --llama-server "${llama_server}" \
    --concurrency 1,2,4 \
    --repetitions 3 \
    --warmup 2 \
    --min-success-rate 1.0 \
    --min-citation-hit-rate 0.95 \
    --output "${benchmark_file}"
  record_stage complete

  current_stage="controlled_child_shutdown"
  record_stage started
  stop_monitor_child
  stop_server_child
  record_stage complete

  current_stage="c2_recheck"
  record_stage started
  assert_c2_binding
  assert_artifact_binding
  record_stage complete

  current_stage="collect_rocm_evidence"
  record_stage started
  "${project_dir}/scripts/collect_rocm_evidence.sh" \
    --run-id "${run_id}" \
    --output-dir "${evidence_dir}" \
    --retrieval-file "${retrieval_file}" \
    --quality-file "${quality_file}" \
    --benchmark-file "${benchmark_file}" \
    --monitor-file "${monitor_log}" \
    --server-log "${server_log}" \
    --model-file "${model_file}" \
    --llama-server "${llama_server}"
  record_stage complete
  run_complete=1
)

failed_experiments=()
for experiment in "${selected_experiments[@]}"; do
  set +e
  run_experiment "${experiment}"
  experiment_status=$?
  set -e
  if (( experiment_status == 0 )); then
    echo "experiment=${experiment} status=complete" >> "${matrix_status_file}"
  else
    failed_experiments+=("${experiment}")
    echo "experiment=${experiment} status=failed" >> "${matrix_status_file}"
  fi
done

comparison_failed=0
if [[ "${run_selection}" == "all" ]]; then
  baseline_bundle="${output_root}/A/evidence"
  optimized_bundle="${output_root}/B/evidence"
  comparison_output="${output_root}/A-vs-B-thinking.json"
  if [[ -f "${baseline_bundle}/binding-manifest.txt" \
        && -f "${optimized_bundle}/binding-manifest.txt" ]]; then
    set +e
    assert_c2_binding && assert_artifact_binding && \
      "${python_bin}" "${project_dir}/evaluation/compare_benchmarks.py" \
        --baseline "${baseline_bundle}/agent-benchmark.json" \
        --optimized "${optimized_bundle}/agent-benchmark.json" \
        --baseline-binding "${baseline_bundle}/binding-manifest.txt" \
        --optimized-binding "${optimized_bundle}/binding-manifest.txt" \
        --material-threshold-percent 5.0 \
        --require-accepted \
        --output "${comparison_output}"
    comparison_status=$?
    set -e
    if (( comparison_status == 0 )); then
      echo "formal_comparison=A-vs-B-thinking status=report_written" >> "${matrix_status_file}"
    else
      comparison_failed=1
      echo "formal_comparison=A-vs-B-thinking status=failed exit_code=${comparison_status}" >> "${matrix_status_file}"
    fi
  else
    echo "formal_comparison=A-vs-B-thinking status=skipped_missing_complete_bundle" >> "${matrix_status_file}"
  fi
else
  echo "formal_comparison=A-vs-B-thinking status=not_scheduled_single_run" >> "${matrix_status_file}"
fi

echo "matrix_completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${matrix_status_file}"
if (( ${#failed_experiments[@]} > 0 || comparison_failed != 0 )); then
  echo "failed_experiments=${failed_experiments[*]}" >> "${matrix_status_file}"
  exit 1
fi
echo "failed_experiments=none" >> "${matrix_status_file}"
