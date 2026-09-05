#!/usr/bin/env bash
set -Eeuo pipefail
set -C

usage() {
  echo "Usage: $0 --run-prefix PREFIX --run A|B|C|D|E|F|G|H|all --expected-commit FULL_SHA --expected-model-sha256 SHA256 --expected-llama-server-sha256 SHA256 --output-root NEW_DIRECTORY --model-file GGUF --model-repository REPOSITORY --model-revision REVISION --model-license SPDX --model-quantization QUANTIZATION --llama-server BINARY --llama-cpp-commit COMMIT --llama-build DESCRIPTION [--model-alias NAME] [--model-port PORT] [--context-size TOKENS] [--optimized-context-size TOKENS] [--optimized-context-candidates CSV] [--benchmark-repetitions COUNT] [--dry-run]" >&2
}

run_prefix=""
run_selection="all"
expected_commit=""
expected_model_sha256=""
expected_llama_server_sha256=""
output_root=""
model_file=""
model_repository=""
model_revision=""
model_license=""
model_quantization="Q6_K"
llama_server=""
llama_cpp_commit=""
llama_build=""
model_alias="qwen3.6-35b-a3b-q6k"
model_port="8000"
context_size="16384"
optimized_context_size="8192"
optimized_context_candidates="4096,8192,12288"
log_verbosity="5"
gpu_layers="999"
benchmark_repetitions="3"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --run-prefix|--run|--expected-commit|--expected-model-sha256|--expected-llama-server-sha256|--output-root|--model-file|--model-repository|--model-revision|--model-license|--model-quantization|--llama-server|--llama-cpp-commit|--llama-build|--model-alias|--model-port|--context-size|--optimized-context-size|--optimized-context-candidates|--benchmark-repetitions)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      case "$1" in
        --run-prefix) run_prefix="${2:-}" ;;
        --run) run_selection="${2:-}" ;;
        --expected-commit) expected_commit="${2:-}" ;;
        --expected-model-sha256) expected_model_sha256="${2:-}" ;;
        --expected-llama-server-sha256) expected_llama_server_sha256="${2:-}" ;;
        --output-root) output_root="${2:-}" ;;
        --model-file) model_file="${2:-}" ;;
        --model-repository) model_repository="${2:-}" ;;
        --model-revision) model_revision="${2:-}" ;;
        --model-license) model_license="${2:-}" ;;
        --model-quantization) model_quantization="${2:-}" ;;
        --llama-server) llama_server="${2:-}" ;;
        --llama-cpp-commit) llama_cpp_commit="${2:-}" ;;
        --llama-build) llama_build="${2:-}" ;;
        --model-alias) model_alias="${2:-}" ;;
        --model-port) model_port="${2:-}" ;;
        --context-size) context_size="${2:-}" ;;
        --optimized-context-size) optimized_context_size="${2:-}" ;;
        --optimized-context-candidates) optimized_context_candidates="${2:-}" ;;
        --benchmark-repetitions) benchmark_repetitions="${2:-}" ;;
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
  A|B|C|D|E|F|G|H|all) ;;
  *)
    echo "--run must be A, B, C, D, E, F, G, H, or all" >&2
    exit 3
    ;;
esac
if [[ ! "${expected_commit}" =~ ^[0-9a-f]{40,64}$ ]]; then
  echo "--expected-commit must be a full lowercase Git object ID" >&2
  exit 3
fi
if [[ ! "${expected_model_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "--expected-model-sha256 must be a lowercase SHA256" >&2
  exit 3
fi
if [[ ! "${expected_llama_server_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "--expected-llama-server-sha256 must be a lowercase SHA256" >&2
  exit 3
fi
if [[ ! "${model_revision}" =~ ^[0-9a-f]{40,64}$ ]]; then
  echo "--model-revision must be a full lowercase revision hash" >&2
  exit 3
fi
if [[ ! "${llama_cpp_commit}" =~ ^[0-9a-f]{40,64}$ ]]; then
  echo "--llama-cpp-commit must be a full lowercase Git object ID" >&2
  exit 3
fi
if [[ -z "${output_root}" || -z "${model_file}" || -z "${llama_server}" \
      || -z "${model_repository}" || -z "${model_license}" || -z "${llama_build}" ]]; then
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
if [[ ! "${model_quantization}" =~ ^Q[0-9][A-Za-z0-9_-]{0,31}$ ]]; then
  echo "--model-quantization must be an explicit Q-level such as Q6_K" >&2
  exit 3
fi
if [[ ! "${context_size}" =~ ^[1-9][0-9]{0,8}$ \
      || ! "${optimized_context_size}" =~ ^[1-9][0-9]{0,8}$ ]]; then
  echo "--context-size and --optimized-context-size must be positive integers" >&2
  exit 3
fi
if (( optimized_context_size >= context_size )); then
  echo "--optimized-context-size must be smaller than --context-size" >&2
  exit 3
fi
if [[ ! "${benchmark_repetitions}" =~ ^[1-9][0-9]{0,5}$ ]] \
    || (( benchmark_repetitions < 3 )); then
  echo "--benchmark-repetitions must be an integer of at least 3" >&2
  exit 3
fi
IFS=, read -r -a declared_context_candidates <<<"${optimized_context_candidates}"
if (( ${#declared_context_candidates[@]} == 0 )); then
  echo "--optimized-context-candidates must not be empty" >&2
  exit 3
fi
previous_context_candidate=0
optimized_context_declared=0
for context_candidate in "${declared_context_candidates[@]}"; do
  if [[ ! "${context_candidate}" =~ ^[1-9][0-9]{0,8}$ ]]; then
    echo "--optimized-context-candidates must contain positive integers" >&2
    exit 3
  fi
  if (( context_candidate <= previous_context_candidate )); then
    echo "--optimized-context-candidates must be unique and ascending" >&2
    exit 3
  fi
  if (( context_candidate >= context_size )); then
    echo "Every optimized context candidate must be smaller than --context-size" >&2
    exit 3
  fi
  if (( context_candidate == optimized_context_size )); then
    optimized_context_declared=1
  fi
  previous_context_candidate="${context_candidate}"
done
if (( optimized_context_declared == 0 )); then
  echo "--optimized-context-size must be present in --optimized-context-candidates" >&2
  exit 3
fi
for supplied_path in "${output_root}" "${model_file}" "${llama_server}"; do
  if [[ "${supplied_path}" == *$'\n'* || "${supplied_path}" == *$'\r'* ]]; then
    echo "Matrix paths must not contain CR or LF characters" >&2
    exit 3
  fi
done
for provenance_value in \
  "${model_repository}" \
  "${model_license}" \
  "${model_quantization}" \
  "${llama_build}"; do
  if [[ "${provenance_value}" == *$'\n'* || "${provenance_value}" == *$'\r'* ]]; then
    echo "Provenance values must not contain CR or LF characters" >&2
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

assert_artifact_binding() {
  local current_model_sha256 current_llama_sha256
  current_model_sha256="$(sha256sum -- "${model_file}" | awk '{print $1}')"
  current_llama_sha256="$(sha256sum -- "${llama_server}" | awk '{print $1}')"
  if [[ "${current_model_sha256}" != "${expected_model_sha256}" ]]; then
    echo "Model SHA256 ${current_model_sha256} does not match expected ${expected_model_sha256}" >&2
    return 1
  fi
  if [[ "${current_llama_sha256}" != "${expected_llama_server_sha256}" ]]; then
    echo "llama-server SHA256 ${current_llama_sha256} does not match expected ${expected_llama_server_sha256}" >&2
    return 1
  fi
}

assert_artifact_binding
assert_c2_binding
c2_project_tree="$(git -C "${project_dir}" rev-parse "HEAD:${project_prefix}")"
pinned_model_sha256="${expected_model_sha256}"
pinned_llama_sha256="${expected_llama_server_sha256}"

configure_experiment() {
  local experiment="$1"
  # Each adjacent pair changes exactly one declared optimization group.
  case "${experiment}" in
    A) thinking="on";  flash_attn="off"; batch_size="256"; ubatch_size="64";  fused_plan_evidence="0"; experiment_context_size="${context_size}";           parallel_slots="1"; cache_type_k="f16";  cache_type_v="f16" ;;
    B) thinking="off"; flash_attn="off"; batch_size="256"; ubatch_size="64";  fused_plan_evidence="0"; experiment_context_size="${context_size}";           parallel_slots="1"; cache_type_k="f16";  cache_type_v="f16" ;;
    C) thinking="off"; flash_attn="on";  batch_size="256"; ubatch_size="64";  fused_plan_evidence="0"; experiment_context_size="${context_size}";           parallel_slots="1"; cache_type_k="f16";  cache_type_v="f16" ;;
    D) thinking="off"; flash_attn="on";  batch_size="512"; ubatch_size="128"; fused_plan_evidence="0"; experiment_context_size="${context_size}";           parallel_slots="1"; cache_type_k="f16";  cache_type_v="f16" ;;
    E) thinking="off"; flash_attn="on";  batch_size="512"; ubatch_size="128"; fused_plan_evidence="1"; experiment_context_size="${context_size}";           parallel_slots="1"; cache_type_k="f16";  cache_type_v="f16" ;;
    F) thinking="off"; flash_attn="on";  batch_size="512"; ubatch_size="128"; fused_plan_evidence="1"; experiment_context_size="${optimized_context_size}"; parallel_slots="1"; cache_type_k="f16";  cache_type_v="f16" ;;
    G) thinking="off"; flash_attn="on";  batch_size="512"; ubatch_size="128"; fused_plan_evidence="1"; experiment_context_size="${optimized_context_size}"; parallel_slots="4"; cache_type_k="f16";  cache_type_v="f16" ;;
    H) thinking="off"; flash_attn="on";  batch_size="512"; ubatch_size="128"; fused_plan_evidence="1"; experiment_context_size="${optimized_context_size}"; parallel_slots="4"; cache_type_k="q8_0"; cache_type_v="q8_0" ;;
    *) return 2 ;;
  esac
}

if [[ "${run_selection}" == "all" ]]; then
  selected_experiments=(A B C D E F G H)
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
  echo "model_alias=${model_alias} context_size=${experiment_context_size}"
  echo "model_sha256=${pinned_model_sha256} llama_server_sha256=${pinned_llama_sha256}"
  echo "model_repository=${model_repository} model_revision=${model_revision} model_license=${model_license} model_quantization=${model_quantization}"
  echo "optimized_context_candidates=${optimized_context_candidates}"
  if [[ "${run_selection}" == "all" ]]; then
    echo "optimized_context_selection=automatic_from_full_score_run_E_before_F"
  else
    echo "optimized_context_selection=explicit_for_single_run"
  fi
  echo "benchmark_repetitions=${benchmark_repetitions}"
  echo "llama_cpp_commit=${llama_cpp_commit} llama_build=${llama_build}"
  echo "thinking=${thinking} fused_plan_evidence=${fused_plan_evidence} flash_attn=${flash_attn} context_size=${experiment_context_size} batch=${batch_size} ubatch=${ubatch_size} parallel=${parallel_slots} gpu_layers=${gpu_layers} cache_type_k=${cache_type_k} cache_type_v=${cache_type_v} log_verbosity=${log_verbosity}"
  echo "stages=serve_model,monitor_rocm,retrieval,agent_quality,stress,benchmark,context_evidence_if_E_or_F,c2_live_recheck,collect_live_rocm_evidence,controlled_child_shutdown,c2_final_recheck,collect_rocm_evidence"
  if [[ "${run_selection}" == "all" ]]; then
    echo "formal_comparisons=A-vs-B-thinking,B-vs-C-flash-attention,C-vs-D-batch,D-vs-E-fused-plan-evidence,E-vs-F-context-size,F-vs-G-parallel,G-vs-H-kv-cache"
  else
    echo "formal_comparisons=not_scheduled_for_single_run"
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
  echo "artifact_retention=preserve_all_outputs_on_failure"
} > "${matrix_status_file}"

run_experiment() (
  set -Eeuo pipefail
  set -C
  local experiment="$1"
  local run_id="${run_prefix}-${experiment}"
  local run_dir="${output_root}/${experiment}"
  local server_log="${run_dir}/llama-server.log"
  local monitor_log="${run_dir}/rocm-monitor.log"
  local live_evidence_file="${run_dir}/live-rocm.log"
  local stop_file="${run_dir}/monitor.stop"
  local retrieval_file="${run_dir}/retrieval.json"
  local quality_file="${run_dir}/agent-quality.json"
  local stress_file="${run_dir}/stress.json"
  local benchmark_file="${run_dir}/agent-benchmark.json"
  local context_selection_file="${run_dir}/context-selection.json"
  local context_proof_file="${run_dir}/context-proof.json"
  local evidence_dir="${run_dir}/evidence"
  local quality_negative_dir="${run_dir}/quality-negative"
  local status_file="${run_dir}/orchestration-status.log"
  local manifest_file="${run_dir}/experiment-manifest.txt"
  local runtime_instance_file="${run_dir}/runtime-instance.json"
  local server_pid=""
  local monitor_pid=""
  local server_active=0
  local monitor_active=0
  local run_complete=0
  local current_stage="preflight"
  local -a evidence_arguments=()
  local -a service_configuration_arguments=()
  local expected_service_configuration_sha256=""

  configure_experiment "${experiment}"
  expected_service_configuration_sha256="$(
    "${python_bin}" - \
      "${experiment_context_size}" "${parallel_slots}" "${batch_size}" \
      "${ubatch_size}" "${flash_attn}" "${gpu_layers}" \
      "${cache_type_k}" "${cache_type_v}" "${log_verbosity}" <<'PY_CONFIG_SHA'
import hashlib
import json
import sys

ctx, parallel, batch, ubatch, flash, gpu, cache_k, cache_v, log = sys.argv[1:]
value = {
    "ctx": int(ctx),
    "parallel": int(parallel),
    "batch": int(batch),
    "ubatch": int(ubatch),
    "flash_attn": flash,
    "gpu_layers": int(gpu),
    "cache_type_k": cache_k,
    "cache_type_v": cache_v,
    "log_verbosity": int(log),
}
canonical = json.dumps(
    value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
).encode("ascii")
print(hashlib.sha256(canonical).hexdigest())
PY_CONFIG_SHA
  )"
  mkdir -m 0700 -- "${run_dir}"
  {
    echo "schema_version=2"
    echo "experiment=${experiment}"
    echo "run_id=${run_id}"
    echo "c2_binding_status=verified"
    echo "commit=${expected_commit}"
    echo "project_tree=${c2_project_tree}"
    echo "model_file=${model_file}"
    echo "model_sha256=${pinned_model_sha256}"
    echo "model_repository=${model_repository}"
    echo "model_revision=${model_revision}"
    echo "model_license=${model_license}"
    echo "model_quantization=${model_quantization}"
    echo "llama_server=${llama_server}"
    echo "llama_server_sha256=${pinned_llama_sha256}"
    echo "llama_cpp_commit=${llama_cpp_commit}"
    echo "llama_build=${llama_build}"
    echo "model_alias=${model_alias}"
    echo "context_size=${experiment_context_size}"
    echo "optimized_context_candidates=${optimized_context_candidates}"
    echo "benchmark_repetitions=${benchmark_repetitions}"
    echo "thinking=${thinking}"
    echo "fused_plan_evidence=${fused_plan_evidence}"
    echo "flash_attn=${flash_attn}"
    echo "batch_size=${batch_size}"
    echo "ubatch_size=${ubatch_size}"
    echo "parallel_slots=${parallel_slots}"
    echo "gpu_layers=${gpu_layers}"
    echo "cache_type_k=${cache_type_k}"
    echo "cache_type_v=${cache_type_v}"
    echo "log_verbosity=${log_verbosity}"
    echo "service_configuration_sha256=${expected_service_configuration_sha256}"
    echo "artifact_retention=preserve_all_outputs_on_failure"
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
    CONTEXT_SIZE="${experiment_context_size}" \
    EVIDENCE_RUN_ID="${run_id}" \
    RADEONSTAY_DEMO_RUN_ID="${run_id}" \
    RADEONSTAY_RUNTIME_INSTANCE_PATH="${runtime_instance_file}" \
    FLASH_ATTN="${flash_attn}" \
    PARALLEL_SLOTS="${parallel_slots}" \
    BATCH_SIZE="${batch_size}" \
    UBATCH_SIZE="${ubatch_size}" \
    GPU_LAYERS="${gpu_layers}" \
    CACHE_TYPE_K="${cache_type_k}" \
    CACHE_TYPE_V="${cache_type_v}" \
    EXPECTED_SERVICE_CONFIGURATION_SHA256="${expected_service_configuration_sha256}" \
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
    RADEONSTAY_FUSED_PLAN_EVIDENCE="${fused_plan_evidence}"
    RADEONSTAY_DEMO_RUN_ID="${run_id}"
    RADEONSTAY_RUNTIME_INSTANCE_PATH="${runtime_instance_file}"
  )
  service_configuration_arguments=(
    --experiment "${experiment}"
    --context-size "${experiment_context_size}"
    --parallel-slots "${parallel_slots}"
    --batch-size "${batch_size}"
    --ubatch-size "${ubatch_size}"
    --flash-attn "${flash_attn}"
    --gpu-layers "${gpu_layers}"
    --cache-type-k "${cache_type_k}"
    --cache-type-v "${cache_type_v}"
    --log-verbosity "${log_verbosity}"
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
  set +e
  env "${common_environment[@]}" "${python_bin}" \
    "${project_dir}/evaluation/run_agent_eval.py" \
    --run-id "${run_id}" \
    --model-file "${model_file}" \
    --llama-server "${llama_server}" \
    "${service_configuration_arguments[@]}" \
    --output "${quality_file}"
  quality_status=$?
  set -e
  if (( quality_status != 0 )); then
    if [[ "${experiment}" != "A" ]]; then
      echo "Only matrix row A may be retained as a quality negative" >&2
      return "${quality_status}"
    fi
    echo "at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) stage=${current_stage} status=quality_rejected_preserving_bound_negative" >> "${status_file}"

    current_stage="controlled_child_shutdown_for_quality_negative"
    record_stage started
    stop_monitor_child
    stop_server_child
    record_stage complete

    current_stage="build_quality_negative_evidence"
    record_stage started
    assert_c2_binding
    assert_artifact_binding
    "${python_bin}" "${project_dir}/evaluation/quality_negative_evidence.py" \
      --run-id "${run_id}" \
      --expected-commit "${expected_commit}" \
      --expected-project-tree "${c2_project_tree}" \
      --retrieval-file "${retrieval_file}" \
      --quality-file "${quality_file}" \
      --monitor-file "${monitor_log}" \
      --server-log "${server_log}" \
      --runtime-instance-file "${runtime_instance_file}" \
      --output-dir "${quality_negative_dir}"
    record_stage complete

    current_stage="final_source_artifact_binding_for_quality_negative"
    record_stage started
    assert_c2_binding
    assert_artifact_binding
    record_stage complete
    run_complete=1
    return 0
  fi
  record_stage complete

  current_stage="stress"
  record_stage started
  env "${common_environment[@]}" "${python_bin}" \
    "${project_dir}/evaluation/run_stress_eval.py" \
    --run-id "${run_id}" \
    --model-file "${model_file}" \
    --llama-server "${llama_server}" \
    "${service_configuration_arguments[@]}" \
    --output "${stress_file}"
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
    --repetitions "${benchmark_repetitions}" \
    --warmup 3 \
    --min-success-rate 1.0 \
    --min-citation-hit-rate 1.0 \
    "${service_configuration_arguments[@]}" \
    --output "${benchmark_file}"
  record_stage complete

  if [[ "${experiment}" == "E" ]]; then
    current_stage="context_selection"
    record_stage started
    "${python_bin}" "${project_dir}/evaluation/validate_context_window.py" \
      --quality-report "${quality_file}" \
      --benchmark-report "${benchmark_file}" \
      --allow-prebundle \
      --candidate-context-sizes "${optimized_context_candidates}" \
      --output "${context_selection_file}"
    record_stage complete
  elif [[ "${experiment}" == "F" ]]; then
    current_stage="context_proof"
    record_stage started
    "${python_bin}" "${project_dir}/evaluation/validate_context_window.py" \
      --quality-report "${quality_file}" \
      --benchmark-report "${benchmark_file}" \
      --allow-prebundle \
      --selected-context-size "${optimized_context_size}" \
      --candidate-context-sizes "${optimized_context_candidates}" \
      --output "${context_proof_file}"
    record_stage complete
  else
    current_stage="context_selection_and_proof"
    echo "at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) stage=${current_stage} status=not_assessed_not_run_e_or_f" >> "${status_file}"
  fi

  evidence_arguments=(
    --run-id "${run_id}"
    --output-dir "${evidence_dir}"
    --live-evidence-file "${live_evidence_file}"
    --retrieval-file "${retrieval_file}"
    --quality-file "${quality_file}"
    --stress-file "${stress_file}"
    --benchmark-file "${benchmark_file}"
    --monitor-file "${monitor_log}"
    --server-log "${server_log}"
    --runtime-instance-file "${runtime_instance_file}"
    --model-file "${model_file}"
    --expected-model-sha256 "${expected_model_sha256}"
    --model-repository "${model_repository}"
    --model-revision "${model_revision}"
    --model-license "${model_license}"
    --model-quantization "${model_quantization}"
    --llama-server "${llama_server}"
    --expected-llama-server-sha256 "${expected_llama_server_sha256}"
    --llama-cpp-commit "${llama_cpp_commit}"
    --llama-build "${llama_build}"
    --python-executable "${python_bin}"
  )
  if [[ "${experiment}" == "E" ]]; then
    evidence_arguments+=(--context-selection-file "${context_selection_file}")
  elif [[ "${experiment}" == "F" ]]; then
    evidence_arguments+=(--context-proof-file "${context_proof_file}")
  fi

  current_stage="c2_live_recheck"
  record_stage started
  assert_c2_binding
  assert_artifact_binding
  record_stage complete

  current_stage="collect_live_rocm_evidence"
  record_stage started
  "${project_dir}/scripts/collect_rocm_evidence.sh" \
    --phase live \
    "${evidence_arguments[@]}"
  record_stage complete

  current_stage="controlled_child_shutdown"
  record_stage started
  stop_monitor_child
  stop_server_child
  record_stage complete

  current_stage="c2_final_recheck"
  record_stage started
  assert_c2_binding
  assert_artifact_binding
  record_stage complete

  current_stage="collect_rocm_evidence"
  record_stage started
  "${project_dir}/scripts/collect_rocm_evidence.sh" \
    --phase final \
    "${evidence_arguments[@]}"
  record_stage complete
  run_complete=1
)

failed_experiments=()
quality_negative_experiments=()
evidence_validation_failed=0
for experiment in "${selected_experiments[@]}"; do
  set +e
  run_experiment "${experiment}"
  experiment_status=$?
  set -e
  if (( experiment_status == 0 )); then
    if [[ -f "${output_root}/${experiment}/quality-negative/manifest.json" ]]; then
      if [[ "${experiment}" != "A" ]]; then
        failed_experiments+=("${experiment}-unexpected-quality-negative")
        echo "experiment=${experiment} status=failed_unexpected_quality_negative" >> "${matrix_status_file}"
        continue
      fi
      quality_negative_experiments+=("${experiment}")
      echo "experiment=${experiment} status=quality_rejected_negative_preserved" >> "${matrix_status_file}"
    else
      echo "experiment=${experiment} status=complete" >> "${matrix_status_file}"
    fi
    if [[ "${experiment}" == "E" || "${experiment}" == "F" ]]; then
      bound_context_output="${output_root}/${experiment}/context-bound-validation.json"
      bound_context_arguments=(
        --quality-report "${output_root}/${experiment}/evidence/agent-quality.json"
        --benchmark-report "${output_root}/${experiment}/evidence/agent-benchmark.json"
        --binding "${output_root}/${experiment}/evidence/binding-manifest.txt"
        --candidate-context-sizes "${optimized_context_candidates}"
        --output "${bound_context_output}"
      )
      if [[ "${experiment}" == "F" ]]; then
        bound_context_arguments+=(--selected-context-size "${optimized_context_size}")
      fi
      set +e
      "${python_bin}" "${project_dir}/evaluation/validate_context_window.py" \
        "${bound_context_arguments[@]}"
      context_binding_status=$?
      set -e
      if (( context_binding_status != 0 )); then
        failed_experiments+=("${experiment}-bound-context-validation")
        evidence_validation_failed=1
        echo "context_validation=failed experiment=${experiment} artifacts=preserved source=${bound_context_output}" >> "${matrix_status_file}"
      elif [[ "${experiment}" == "E" ]]; then
        selected_context_from_e="$(
          "${python_bin}" -c \
            'import json, sys; value=json.load(open(sys.argv[1], encoding="utf-8"))["minimum_safe_candidate"]; assert isinstance(value, int) and value > 0; print(value)' \
            "${bound_context_output}"
        )"
        optimized_context_size="${selected_context_from_e}"
        echo "context_selection=accepted_bound_bundle selected_context_size=${optimized_context_size} source=${bound_context_output}" >> "${matrix_status_file}"
      else
        echo "context_proof=accepted_bound_bundle selected_context_size=${optimized_context_size} source=${bound_context_output}" >> "${matrix_status_file}"
      fi
    fi
  else
    failed_experiments+=("${experiment}")
    echo "experiment=${experiment} status=failed" >> "${matrix_status_file}"
  fi
done

comparison_failed="${evidence_validation_failed}"
if [[ "${run_selection}" == "all" ]]; then
  reference_experiment="A"
  expected_candidate_count=8
  expected_adjacent_comparison_count=7
  winner_quality_negative_arguments=()
  if (( ${#quality_negative_experiments[@]} == 1 )) \
      && [[ "${quality_negative_experiments[0]}" == "A" ]]; then
    reference_experiment="B"
    expected_candidate_count=7
    expected_adjacent_comparison_count=6
    winner_quality_negative_arguments=(
      --quality-negative A "${output_root}/A/quality-negative/manifest.json"
    )
    echo "quality_transition=A-rejected-to-B-first-300-reference" >> "${matrix_status_file}"
  elif (( ${#quality_negative_experiments[@]} != 0 )); then
    comparison_failed=1
    echo "quality_transition=invalid_negative_set labels=${quality_negative_experiments[*]}" >> "${matrix_status_file}"
  fi
  complete_adjacent_comparison_count=0
  if [[ "${reference_experiment}" == "A" ]]; then
    formal_comparison_pairs=(
      "A:B:thinking"
      "B:C:flash-attention"
      "C:D:batch"
      "D:E:fused-plan-evidence"
      "E:F:context-size"
      "F:G:parallel"
      "G:H:kv-cache"
    )
  else
    formal_comparison_pairs=(
      "B:C:flash-attention"
      "C:D:batch"
      "D:E:fused-plan-evidence"
      "E:F:context-size"
      "F:G:parallel"
      "G:H:kv-cache"
    )
  fi
  for comparison_spec in "${formal_comparison_pairs[@]}"; do
    IFS=: read -r baseline_experiment optimized_experiment comparison_label \
      <<<"${comparison_spec}"
    comparison_name="${baseline_experiment}-vs-${optimized_experiment}-${comparison_label}"
    baseline_bundle="${output_root}/${baseline_experiment}/evidence"
    optimized_bundle="${output_root}/${optimized_experiment}/evidence"
    comparison_output="${output_root}/${comparison_name}.json"
    if [[ -f "${baseline_bundle}/agent-benchmark.json" \
          && -f "${baseline_bundle}/binding-manifest.txt" \
          && -f "${optimized_bundle}/agent-benchmark.json" \
          && -f "${optimized_bundle}/binding-manifest.txt" ]]; then
      set +e
      assert_c2_binding && assert_artifact_binding && \
        "${python_bin}" "${project_dir}/evaluation/compare_benchmarks.py" \
          --baseline "${baseline_bundle}/agent-benchmark.json" \
          --optimized "${optimized_bundle}/agent-benchmark.json" \
          --baseline-binding "${baseline_bundle}/binding-manifest.txt" \
          --optimized-binding "${optimized_bundle}/binding-manifest.txt" \
          --material-threshold-percent 5.0 \
          --maximum-vram-percent 90.0 \
          --output "${comparison_output}"
      comparison_status=$?
      set -e
      if (( comparison_status == 0 )); then
        set +e
        comparison_assessment="$(
          "${python_bin}" -c \
            'import json, sys
assessment = json.load(open(sys.argv[1], encoding="utf-8")).get("assessment")
if not isinstance(assessment, dict):
    raise ValueError("missing assessment object")
accepted = assessment.get("accepted")
winner = assessment.get("optimization_winner")
if accepted is True and winner == "optimized":
    print("accepted")
elif accepted is False and winner == "not_accepted":
    print("negative_experiment")
else:
    raise ValueError("invalid assessment result")' \
            "${comparison_output}"
        )"
        assessment_status=$?
        set -e
        if (( assessment_status != 0 )); then
          comparison_failed=1
          echo "formal_comparison=${comparison_name} status=failed_invalid_report artifacts=preserved report=${comparison_output}" >> "${matrix_status_file}"
        elif [[ "${comparison_assessment}" == "accepted" ]]; then
          complete_adjacent_comparison_count=$((complete_adjacent_comparison_count + 1))
          echo "formal_comparison=${comparison_name} status=accepted report=${comparison_output}" >> "${matrix_status_file}"
        else
          complete_adjacent_comparison_count=$((complete_adjacent_comparison_count + 1))
          echo "formal_comparison=${comparison_name} status=negative_experiment artifacts=preserved report=${comparison_output}" >> "${matrix_status_file}"
        fi
      else
        comparison_failed=1
        echo "formal_comparison=${comparison_name} status=failed exit_code=${comparison_status} artifacts=preserved report=${comparison_output}" >> "${matrix_status_file}"
      fi
    else
      comparison_failed=1
      echo "formal_comparison=${comparison_name} status=failed_missing_complete_bundle artifacts=preserved" >> "${matrix_status_file}"
    fi
  done
  if [[ "${reference_experiment}" == "A" ]] \
      && (( complete_adjacent_comparison_count != 7 )); then
    comparison_failed=1
    echo "formal_comparisons=not_assessed_missing_complete_adjacent_comparison complete=${complete_adjacent_comparison_count} required=7 artifacts=preserved" >> "${matrix_status_file}"
  elif [[ "${reference_experiment}" == "B" ]] \
      && (( complete_adjacent_comparison_count != 6 )); then
    comparison_failed=1
    echo "formal_comparisons=not_assessed_missing_complete_adjacent_comparison complete=${complete_adjacent_comparison_count} required=6 artifacts=preserved" >> "${matrix_status_file}"
  fi

  winner_candidate_arguments=()
  complete_winner_candidate_count=0
  for experiment in A B C D E F G H; do
    if [[ "${reference_experiment}" == "B" && "${experiment}" == "A" ]]; then
      continue
    fi
    candidate_bundle="${output_root}/${experiment}/evidence"
    if [[ -f "${candidate_bundle}/agent-benchmark.json" \
          && -f "${candidate_bundle}/binding-manifest.txt" ]]; then
      winner_candidate_arguments+=(
        --candidate "${experiment}"
        "${candidate_bundle}/agent-benchmark.json"
        "${candidate_bundle}/binding-manifest.txt"
      )
      complete_winner_candidate_count=$((complete_winner_candidate_count + 1))
    fi
  done
  winner_output="${output_root}/winner-selection.json"
  reference_candidate_bundle="${output_root}/${reference_experiment}/evidence"
  baseline_complete=0
  if [[ "${reference_experiment}" == "A" \
        && -f "${output_root}/A/evidence/agent-benchmark.json" \
        && -f "${output_root}/A/evidence/binding-manifest.txt" ]]; then
    baseline_complete=1
  elif [[ "${reference_experiment}" == "B" \
          && -f "${output_root}/A/quality-negative/manifest.json" \
          && -f "${output_root}/B/evidence/agent-benchmark.json" \
          && -f "${output_root}/B/evidence/binding-manifest.txt" ]]; then
    baseline_complete=1
  fi
  if (( baseline_complete == 0 )); then
    comparison_failed=1
    echo "winner_selection=not_assessed_missing_complete_baseline reference=${reference_experiment} artifacts=preserved" >> "${matrix_status_file}"
  elif (( ${#failed_experiments[@]} != 0 || evidence_validation_failed != 0 )); then
    comparison_failed=1
    echo "winner_selection=not_assessed_matrix_execution_or_evidence_failure complete_bundles=${complete_winner_candidate_count} artifacts=preserved" >> "${matrix_status_file}"
  elif [[ "${reference_experiment}" == "A" ]] \
      && (( complete_winner_candidate_count != 8 )); then
    comparison_failed=1
    echo "winner_selection=not_assessed_missing_complete_bundle complete_bundles=${complete_winner_candidate_count} required=8 artifacts=preserved" >> "${matrix_status_file}"
  elif [[ "${reference_experiment}" == "B" ]] \
      && (( complete_winner_candidate_count != 7 )); then
    comparison_failed=1
    echo "winner_selection=not_assessed_missing_complete_bundle complete_bundles=${complete_winner_candidate_count} required=7 artifacts=preserved" >> "${matrix_status_file}"
  elif [[ ! -f "${reference_candidate_bundle}/agent-benchmark.json" \
        || ! -f "${reference_candidate_bundle}/binding-manifest.txt" ]]; then
    comparison_failed=1
    echo "winner_selection=not_assessed_missing_complete_reference reference=${reference_experiment} complete_bundles=${complete_winner_candidate_count} artifacts=preserved" >> "${matrix_status_file}"
  elif (( complete_adjacent_comparison_count != expected_adjacent_comparison_count )); then
    comparison_failed=1
    echo "winner_selection=not_assessed_missing_complete_adjacent_comparison complete=${complete_adjacent_comparison_count} required=${expected_adjacent_comparison_count} artifacts=preserved" >> "${matrix_status_file}"
  elif (( comparison_failed != 0 )); then
    comparison_failed=1
    echo "winner_selection=not_assessed_malformed_complete_evidence artifacts=preserved" >> "${matrix_status_file}"
  else
    set +e
    assert_c2_binding && assert_artifact_binding && \
      "${python_bin}" "${project_dir}/evaluation/select_winner.py" \
        "${winner_candidate_arguments[@]}" \
        "${winner_quality_negative_arguments[@]}" \
        --material-threshold-percent 5.0 \
        --maximum-vram-percent 90.0 \
        --p95-slack-percent 5.0 \
        --require-accepted \
        --output "${winner_output}"
    winner_selection_status=$?
    set -e
    if (( winner_selection_status == 0 )); then
      echo "winner_selection=accepted report=${winner_output}" >> "${matrix_status_file}"
    else
      comparison_failed=1
      echo "winner_selection=failed exit_code=${winner_selection_status} artifacts=preserved report=${winner_output}" >> "${matrix_status_file}"
    fi
  fi
else
  echo "formal_comparisons=not_scheduled_single_run" >> "${matrix_status_file}"
fi

echo "matrix_completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${matrix_status_file}"
if (( ${#quality_negative_experiments[@]} != 0 )); then
  echo "quality_negative_experiments=${quality_negative_experiments[*]}" >> "${matrix_status_file}"
  echo "quality_negative_artifacts=bound_and_preserved" >> "${matrix_status_file}"
else
  echo "quality_negative_experiments=none" >> "${matrix_status_file}"
fi
if (( ${#failed_experiments[@]} != 0 )); then
  echo "negative_or_incomplete_experiments=${failed_experiments[*]}" >> "${matrix_status_file}"
  echo "negative_experiment_artifacts=preserved" >> "${matrix_status_file}"
fi
if (( comparison_failed != 0 || ${#failed_experiments[@]} != 0 )); then
  if (( ${#failed_experiments[@]} == 0 )); then
    echo "failed_experiments=none" >> "${matrix_status_file}"
  else
    echo "failed_experiments=${failed_experiments[*]}" >> "${matrix_status_file}"
  fi
  echo "failure_artifacts=preserved" >> "${matrix_status_file}"
  exit 1
fi
echo "failed_experiments=none" >> "${matrix_status_file}"
if [[ "${run_selection}" == "all" ]]; then
  echo "matrix_status=accepted_with_complete_winner_selection" >> "${matrix_status_file}"
else
  echo "winner_selection=not_assessed_single_experiment" >> "${matrix_status_file}"
  echo "matrix_status=complete_single_experiment" >> "${matrix_status_file}"
fi
