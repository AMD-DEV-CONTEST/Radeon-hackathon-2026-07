#!/usr/bin/env bash
set -euo pipefail
set -C

usage() {
  echo "Usage: $0 --phase live|final --run-id RUN_ID --output-dir NEW_DIRECTORY --live-evidence-file FILE --retrieval-file FILE --quality-file FILE --stress-file FILE --benchmark-file FILE --monitor-file FILE --server-log FILE --runtime-instance-file FILE --model-file FILE --expected-model-sha256 SHA256 --model-repository REPOSITORY --model-revision REVISION --model-license SPDX --model-quantization QUANTIZATION --llama-server FILE --expected-llama-server-sha256 SHA256 --llama-cpp-commit COMMIT --llama-build DESCRIPTION [--context-selection-file FILE | --context-proof-file FILE] [--python-executable PYTHON]" >&2
}

collection_phase="final"
run_id=""
output_dir=""
live_evidence_file=""
benchmark_file=""
quality_file=""
stress_file=""
context_selection_file=""
context_proof_file=""
retrieval_file=""
monitor_file=""
server_log=""
runtime_instance_file=""
model_file=""
expected_model_sha256=""
model_repository=""
model_revision=""
model_license=""
model_quantization=""
llama_server=""
expected_llama_server_sha256=""
llama_cpp_commit=""
llama_build=""
python_executable="python3"
while [[ $# -gt 0 ]]; do
  if [[ $# -lt 2 ]]; then
    usage
    exit 2
  fi
  case "$1" in
    --phase)
      collection_phase="${2:-}"
      shift 2
      ;;
    --run-id)
      run_id="${2:-}"
      shift 2
      ;;
    --output-dir)
      output_dir="${2:-}"
      shift 2
      ;;
    --live-evidence-file)
      live_evidence_file="${2:-}"
      shift 2
      ;;
    --benchmark-file)
      benchmark_file="${2:-}"
      shift 2
      ;;
    --quality-file)
      quality_file="${2:-}"
      shift 2
      ;;
    --stress-file)
      stress_file="${2:-}"
      shift 2
      ;;
    --context-selection-file)
      context_selection_file="${2:-}"
      shift 2
      ;;
    --context-proof-file)
      context_proof_file="${2:-}"
      shift 2
      ;;
    --retrieval-file)
      retrieval_file="${2:-}"
      shift 2
      ;;
    --monitor-file)
      monitor_file="${2:-}"
      shift 2
      ;;
    --server-log)
      server_log="${2:-}"
      shift 2
      ;;
    --runtime-instance-file)
      runtime_instance_file="${2:-}"
      shift 2
      ;;
    --model-file)
      model_file="${2:-}"
      shift 2
      ;;
    --expected-model-sha256)
      expected_model_sha256="${2:-}"
      shift 2
      ;;
    --model-repository)
      model_repository="${2:-}"
      shift 2
      ;;
    --model-revision)
      model_revision="${2:-}"
      shift 2
      ;;
    --model-license)
      model_license="${2:-}"
      shift 2
      ;;
    --model-quantization)
      model_quantization="${2:-}"
      shift 2
      ;;
    --llama-server)
      llama_server="${2:-}"
      shift 2
      ;;
    --expected-llama-server-sha256)
      expected_llama_server_sha256="${2:-}"
      shift 2
      ;;
    --llama-cpp-commit)
      llama_cpp_commit="${2:-}"
      shift 2
      ;;
    --llama-build)
      llama_build="${2:-}"
      shift 2
      ;;
    --python-executable)
      python_executable="${2:-}"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ ! "${run_id}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$ ]]; then
  echo "Run ID must be 1-48 characters using letters, digits, dot, underscore, colon, or hyphen" >&2
  exit 3
fi
case "${collection_phase}" in
  live|final) ;;
  *)
    echo "--phase must be live or final" >&2
    exit 3
    ;;
esac
if [[ -z "${output_dir}" ]]; then
  usage
  exit 2
fi
if [[ -z "${retrieval_file}" || -z "${quality_file}" || -z "${stress_file}" \
      || -z "${benchmark_file}" \
      || -z "${monitor_file}" \
      || -z "${server_log}" || -z "${model_file}" || -z "${llama_server}" \
      || -z "${runtime_instance_file}" \
      || -z "${live_evidence_file}" \
      || -z "${model_repository}" || -z "${model_license}" \
      || -z "${model_quantization}" || -z "${llama_build}" ]]; then
  echo "A complete evidence bundle requires every artifact argument" >&2
  usage
  exit 2
fi
if [[ -n "${context_selection_file}" && -n "${context_proof_file}" ]]; then
  echo "Context selection and proof artifacts are mutually exclusive" >&2
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
if [[ ! "${model_quantization}" =~ ^Q[0-9][A-Za-z0-9_-]{0,31}$ ]]; then
  echo "--model-quantization must be an explicit Q-level such as Q6_K" >&2
  exit 3
fi
if [[ ! "${llama_cpp_commit}" =~ ^[0-9a-f]{40,64}$ ]]; then
  echo "--llama-cpp-commit must be a full lowercase Git object ID" >&2
  exit 3
fi
for evidence_path in \
  "${output_dir}" \
  "${live_evidence_file}" \
  "${retrieval_file}" \
  "${quality_file}" \
  "${stress_file}" \
  "${context_selection_file}" \
  "${context_proof_file}" \
  "${benchmark_file}" \
  "${monitor_file}" \
  "${server_log}" \
  "${runtime_instance_file}" \
  "${model_file}" \
  "${llama_server}"; do
  if [[ "${evidence_path}" == *$'\n'* || "${evidence_path}" == *$'\r'* ]]; then
    echo "Evidence paths must not contain CR or LF characters" >&2
    exit 3
  fi
done
for provenance_value in \
  "${model_repository}" \
  "${model_license}" \
  "${model_quantization}" \
  "${llama_build}" \
  "${python_executable}"; do
  if [[ "${provenance_value}" == *$'\n'* || "${provenance_value}" == *$'\r'* ]]; then
    echo "Provenance values must not contain CR or LF characters" >&2
    exit 3
  fi
done

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
requirements_lock="${project_dir}/requirements.lock"
if [[ ! -f "${requirements_lock}" ]]; then
  echo "RadeonStay requirements.lock is required for evidence collection" >&2
  exit 3
fi
output_parent="$(dirname -- "${output_dir}")"
if [[ -e "${output_dir}" ]]; then
  echo "Refusing to overwrite existing output path: ${output_dir}" >&2
  exit 3
fi
if [[ ! -d "${output_parent}" ]]; then
  echo "Output parent directory does not exist: ${output_parent}" >&2
  exit 3
fi
output_parent="$(cd -- "${output_parent}" && pwd -P)"
output_dir="${output_parent}/$(basename -- "${output_dir}")"
if [[ "${output_dir}" == *$'\n'* || "${output_dir}" == *$'\r'* ]]; then
  echo "Resolved output path must not contain CR or LF characters" >&2
  exit 3
fi
live_evidence_parent="$(dirname -- "${live_evidence_file}")"
if [[ ! -d "${live_evidence_parent}" ]]; then
  echo "Live-evidence parent directory does not exist: ${live_evidence_parent}" >&2
  exit 3
fi
live_evidence_parent="$(cd -- "${live_evidence_parent}" && pwd -P)"
live_evidence_file="${live_evidence_parent}/$(basename -- "${live_evidence_file}")"
if [[ "${live_evidence_file}" == *$'\n'* || "${live_evidence_file}" == *$'\r'* ]]; then
  echo "Resolved live-evidence path must not contain CR or LF characters" >&2
  exit 3
fi
if [[ "${collection_phase}" == "live" && ( -e "${live_evidence_file}" || -L "${live_evidence_file}" ) ]]; then
  echo "Refusing to overwrite existing live evidence: ${live_evidence_file}" >&2
  exit 3
fi
if [[ "${collection_phase}" == "final" && ! -f "${live_evidence_file}" ]]; then
  echo "Final collection requires complete live evidence: ${live_evidence_file}" >&2
  exit 3
fi
repository_root="$(git -C "${project_dir}" rev-parse --show-toplevel)"
project_prefix="$(git -C "${project_dir}" rev-parse --show-prefix)"
project_prefix="${project_prefix%/}"
if [[ -z "${project_prefix}" ]]; then
  echo "RadeonStay evidence must be collected from a repository subdirectory" >&2
  exit 3
fi
project_status="$(git -C "${project_dir}" status --porcelain=v1 --untracked-files=all -- .)"
if [[ -n "${project_status}" ]]; then
  echo "Official evidence requires tracked, committed, and clean RadeonStay source" >&2
  exit 3
fi
commit="$(git -C "${project_dir}" rev-parse --verify HEAD)"
project_tree="$(git -C "${project_dir}" rev-parse "HEAD:${project_prefix}")"

for required_command in rocminfo rocm-smi git uname sha256sum grep awk sed cp stat; do
  if ! command -v "${required_command}" >/dev/null 2>&1; then
    echo "Required command not found: ${required_command}" >&2
    exit 4
  fi
done
if [[ "${collection_phase}" == "live" ]] \
    && ! command -v curl >/dev/null 2>&1; then
  echo "Required live-collection command not found: curl" >&2
  exit 4
fi
if ! python_executable_path="$(command -v "${python_executable}")"; then
  echo "Python executable not found: ${python_executable}" >&2
  exit 4
fi
python_version="$("${python_executable_path}" --version 2>&1)"
if [[ -z "${python_version}" || "${python_version}" == *$'\n'* \
      || "${python_version}" == *$'\r'* ]]; then
  echo "Python version evidence must be one non-empty line" >&2
  exit 4
fi
for artifact in \
  "${retrieval_file}" \
  "${quality_file}" \
  "${stress_file}" \
  "${context_selection_file}" \
  "${context_proof_file}" \
  "${benchmark_file}" \
  "${monitor_file}" \
  "${server_log}" \
  "${runtime_instance_file}" \
  "${model_file}" \
  "${llama_server}"; do
  if [[ -n "${artifact}" && ! -f "${artifact}" ]]; then
    echo "Bound evidence file does not exist: ${artifact}" >&2
    exit 3
  fi
done
retrieval_file="$(cd -- "$(dirname -- "${retrieval_file}")" && pwd -P)/$(basename -- "${retrieval_file}")"
quality_file="$(cd -- "$(dirname -- "${quality_file}")" && pwd -P)/$(basename -- "${quality_file}")"
stress_file="$(cd -- "$(dirname -- "${stress_file}")" && pwd -P)/$(basename -- "${stress_file}")"
if [[ -n "${context_selection_file}" ]]; then
  context_selection_file="$(cd -- "$(dirname -- "${context_selection_file}")" && pwd -P)/$(basename -- "${context_selection_file}")"
fi
if [[ -n "${context_proof_file}" ]]; then
  context_proof_file="$(cd -- "$(dirname -- "${context_proof_file}")" && pwd -P)/$(basename -- "${context_proof_file}")"
fi
benchmark_file="$(cd -- "$(dirname -- "${benchmark_file}")" && pwd -P)/$(basename -- "${benchmark_file}")"
monitor_file="$(cd -- "$(dirname -- "${monitor_file}")" && pwd -P)/$(basename -- "${monitor_file}")"
server_log="$(cd -- "$(dirname -- "${server_log}")" && pwd -P)/$(basename -- "${server_log}")"
runtime_instance_file="$(
  cd -- "$(dirname -- "${runtime_instance_file}")" && pwd -P
)/$(basename -- "${runtime_instance_file}")"
model_file="$(cd -- "$(dirname -- "${model_file}")" && pwd -P)/$(basename -- "${model_file}")"
llama_server="$(cd -- "$(dirname -- "${llama_server}")" && pwd -P)/$(basename -- "${llama_server}")"
for evidence_path in \
  "${retrieval_file}" \
  "${quality_file}" \
  "${stress_file}" \
  "${context_selection_file}" \
  "${context_proof_file}" \
  "${benchmark_file}" \
  "${monitor_file}" \
  "${server_log}" \
  "${runtime_instance_file}" \
  "${model_file}" \
  "${llama_server}"; do
  if [[ "${evidence_path}" == *$'\n'* || "${evidence_path}" == *$'\r'* ]]; then
    echo "Resolved evidence paths must not contain CR or LF characters" >&2
    exit 3
  fi
done
if [[ -L "${runtime_instance_file}" \
      || "$(stat -c '%a' -- "${runtime_instance_file}")" != "600" ]]; then
  echo "Runtime instance manifest must be a private 0600 regular file" >&2
  exit 3
fi
runtime_instance_sha256="$(
  sha256sum -- "${runtime_instance_file}" | awk '{print $1}'
)"
if ! "${python_executable_path}" \
    "${project_dir}/evaluation/runtime_binding_evidence.py" \
    --manifest "${runtime_instance_file}" \
    --run-id "${run_id}" \
    --expected-sha256 "${runtime_instance_sha256}" >/dev/null; then
  echo "Runtime instance manifest failed strict schema or run binding" >&2
  exit 3
fi
if [[ -n "${benchmark_file}" ]] && ! grep -Fq "\"run_id\": \"${run_id}\"" "${benchmark_file}"; then
  echo "Benchmark file does not contain the requested run ID: ${run_id}" >&2
  exit 3
fi
if ! grep -Fq "\"run_id\": \"${run_id}\"" "${stress_file}"; then
  echo "Stress file does not contain the requested run ID: ${run_id}" >&2
  exit 3
fi
if [[ "${collection_phase}" == "live" ]]; then
  model_sha256="$(sha256sum -- "${model_file}" | awk '{print $1}')"
  llama_server_sha256="$(sha256sum -- "${llama_server}" | awk '{print $1}')"
  requirements_lock_sha256="$(sha256sum -- "${requirements_lock}" | awk '{print $1}')"
  if [[ "${model_sha256}" != "${expected_model_sha256}" ]]; then
    echo "Model SHA256 ${model_sha256} does not match expected ${expected_model_sha256}" >&2
    exit 3
  fi
  if [[ "${llama_server_sha256}" != "${expected_llama_server_sha256}" ]]; then
    echo "llama-server SHA256 ${llama_server_sha256} does not match expected ${expected_llama_server_sha256}" >&2
    exit 3
  fi
  if ! grep -Fqx "evidence_run_id=${run_id}" "${server_log}" \
      || ! grep -Fqx "model_path=${model_file}" "${server_log}" \
      || ! grep -Fqx "model_sha256_at_start=${model_sha256}" "${server_log}" \
      || ! grep -Fqx "llama_server_path=${llama_server}" "${server_log}" \
      || ! grep -Fqx "llama_server_sha256_at_start=${llama_server_sha256}" "${server_log}" \
      || ! grep -Fqx "runtime_instance_manifest_sha256=${runtime_instance_sha256}" "${server_log}" \
      || ! grep -Fqx "process_binding_valid=true" "${server_log}" \
      || ! grep -Fqx "listen_socket_binding_valid=true" "${server_log}"; then
    echo "Live server evidence is not bound to the expected run and artifacts" >&2
    exit 3
  fi
  if ! "${python_executable_path}" \
      "${project_dir}/evaluation/runtime_binding_evidence.py" \
      --manifest "${runtime_instance_file}" \
      --run-id "${run_id}" \
      --expected-sha256 "${runtime_instance_sha256}" \
      --verify-listener \
      --timeout-seconds 5 >/dev/null; then
    echo "Runtime instance PID does not own the declared loopback listener" >&2
    exit 3
  fi
  if ! grep -Fqx "run_id=${run_id}" "${monitor_file}" \
      || ! grep -Fq "sample=1 run_id=${run_id} " "${monitor_file}"; then
    echo "Live ROCm monitor has not produced a bound sample" >&2
    exit 3
  fi
  model_base_url="$(sed -n 's/^model_base_url=//p' "${server_log}" | sed -n '1p')"
  if [[ -z "${model_base_url}" ]] \
      || ! curl --fail --silent --show-error --max-time 5 \
        "${model_base_url%/}/models" >/dev/null; then
    echo "Local model endpoint is not reachable during live evidence collection" >&2
    exit 3
  fi
  {
    echo "schema_version=1"
    echo "collector=collect_rocm_evidence.sh"
    echo "phase=live"
    echo "run_id=${run_id}"
    echo "collected_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "model_endpoint=${model_base_url}"
    echo "model_endpoint_status=reachable"
    echo "model_sha256=${model_sha256}"
    echo "llama_server_sha256=${llama_server_sha256}"
    echo "runtime_instance_manifest_sha256=${runtime_instance_sha256}"
    echo "python_executable=${python_executable_path}"
    echo "python_version=${python_version}"
    echo "requirements_lock_sha256=${requirements_lock_sha256}"
    echo "rocminfo_begin"
    LC_ALL=C rocminfo
    echo "rocminfo_end"
    echo "rocm_smi_begin"
    LC_ALL=C rocm-smi
    echo "rocm_smi_end"
    echo "status=complete"
  } > "${live_evidence_file}" 2>&1
  echo "Live ROCm evidence for run ${run_id} written to: ${live_evidence_file}"
  exit 0
fi
if ! grep -Fqx "evidence_log_status=complete" "${server_log}"; then
  echo "Server log is incomplete or the model service is still running" >&2
  exit 3
fi
if [[ -n "${monitor_file}" ]]; then
  if ! grep -Fqx "run_id=${run_id}" "${monitor_file}"; then
    echo "Monitor file does not contain the requested run ID: ${run_id}" >&2
    exit 3
  fi
  if ! grep -Fqx "status=complete" "${monitor_file}"; then
    echo "Monitor file is incomplete: ${monitor_file}" >&2
    exit 3
  fi
fi
if [[ -n "${server_log}" ]] \
    && ! grep -Fqx "evidence_run_id=${run_id}" "${server_log}"; then
  echo "Server log does not contain the requested run ID: ${run_id}" >&2
  exit 3
fi
if [[ -n "${server_log}" && -n "${model_file}" ]] \
    && ! grep -Fqx "model_path=${model_file}" "${server_log}"; then
  echo "Server log is not bound to the requested model file" >&2
  exit 3
fi
if [[ -n "${server_log}" && -n "${llama_server}" ]] \
    && ! grep -Fqx "llama_server_path=${llama_server}" "${server_log}"; then
  echo "Server log is not bound to the requested llama-server binary" >&2
  exit 3
fi

retrieval_sha256="$(sha256sum -- "${retrieval_file}" | awk '{print $1}')"
quality_sha256="$(sha256sum -- "${quality_file}" | awk '{print $1}')"
stress_sha256="$(sha256sum -- "${stress_file}" | awk '{print $1}')"
context_selection_sha256=""
context_proof_sha256=""
if [[ -n "${context_selection_file}" ]]; then
  context_selection_sha256="$(sha256sum -- "${context_selection_file}" | awk '{print $1}')"
fi
if [[ -n "${context_proof_file}" ]]; then
  context_proof_sha256="$(sha256sum -- "${context_proof_file}" | awk '{print $1}')"
fi
benchmark_sha256="$(sha256sum -- "${benchmark_file}" | awk '{print $1}')"
monitor_sha256="$(sha256sum -- "${monitor_file}" | awk '{print $1}')"
server_log_sha256="$(sha256sum -- "${server_log}" | awk '{print $1}')"
model_sha256="$(sha256sum -- "${model_file}" | awk '{print $1}')"
llama_server_sha256="$(sha256sum -- "${llama_server}" | awk '{print $1}')"
requirements_lock_sha256="$(sha256sum -- "${requirements_lock}" | awk '{print $1}')"
runtime_instance_sha256="$(
  sha256sum -- "${runtime_instance_file}" | awk '{print $1}'
)"
if [[ "${model_sha256}" != "${expected_model_sha256}" ]]; then
  echo "Model SHA256 ${model_sha256} does not match expected ${expected_model_sha256}" >&2
  exit 3
fi
if [[ "${llama_server_sha256}" != "${expected_llama_server_sha256}" ]]; then
  echo "llama-server SHA256 ${llama_server_sha256} does not match expected ${expected_llama_server_sha256}" >&2
  exit 3
fi
live_rocm_sha256="$(sha256sum -- "${live_evidence_file}" | awk '{print $1}')"
if ! grep -Fqx "phase=live" "${live_evidence_file}" \
    || ! grep -Fqx "status=complete" "${live_evidence_file}" \
    || ! grep -Fqx "run_id=${run_id}" "${live_evidence_file}" \
    || ! grep -Fqx "model_endpoint_status=reachable" "${live_evidence_file}" \
    || ! grep -Fqx "model_sha256=${model_sha256}" "${live_evidence_file}" \
    || ! grep -Fqx "llama_server_sha256=${llama_server_sha256}" "${live_evidence_file}" \
    || ! grep -Fqx "runtime_instance_manifest_sha256=${runtime_instance_sha256}" "${live_evidence_file}" \
    || ! grep -Fqx "python_executable=${python_executable_path}" "${live_evidence_file}" \
    || ! grep -Fqx "python_version=${python_version}" "${live_evidence_file}" \
    || ! grep -Fqx "requirements_lock_sha256=${requirements_lock_sha256}" "${live_evidence_file}" \
    || ! grep -Fqx "rocminfo_end" "${live_evidence_file}" \
    || ! grep -Fqx "rocm_smi_end" "${live_evidence_file}"; then
  echo "Live ROCm evidence is incomplete or does not match final collection" >&2
  exit 3
fi

source_tree_sha256="$("${python_executable_path}" - \
  "${project_dir}" "${run_id}" "${retrieval_file}" "${quality_file}" "${stress_file}" "${benchmark_file}" \
  "${context_selection_file}" "${context_proof_file}" \
  "${quality_sha256}" "${benchmark_sha256}" "${model_sha256}" "${llama_server_sha256}" \
  "${commit}" "${project_tree}" "${monitor_file}" "${server_log}" \
  "${runtime_instance_file}" "${runtime_instance_sha256}" <<'PY'
import json
import re
import sys
from datetime import datetime
from pathlib import Path

(
    project_text,
    run_id,
    retrieval_text,
    quality_text,
    stress_text,
    benchmark_text,
    context_selection_text,
    context_proof_text,
    quality_sha256,
    benchmark_sha256,
    model_sha256,
    llama_sha256,
    commit,
    project_tree,
    monitor_text,
    server_text,
    runtime_instance_text,
    runtime_instance_sha256,
) = sys.argv[1:]
project = Path(project_text)
sys.path.insert(0, str(project / "src"))
sys.path.insert(0, str(project))
from evaluation.compare_benchmarks import (
    runtime_gpu_summary,
    validate_context_evidence,
    validate_stress_report,
)
from evaluation.runtime_binding_evidence import (
    load_runtime_instance,
    validate_report_runtime_binding,
)
from evaluation.source_provenance import source_tree_sha256
from radeonstay.retrieval import policy_corpus_sha256, validate_policy_directory

retrieval = json.loads(Path(retrieval_text).read_text(encoding="utf-8"))
quality = json.loads(Path(quality_text).read_text(encoding="utf-8"))
stress = json.loads(Path(stress_text).read_text(encoding="utf-8"))
benchmark = json.loads(Path(benchmark_text).read_text(encoding="utf-8"))
runtime_instance = load_runtime_instance(
    Path(runtime_instance_text),
    expected_run_id=run_id,
    expected_sha256=runtime_instance_sha256,
)
if runtime_instance.payload["model_sha256"] != model_sha256:
    raise SystemExit("Runtime-instance model SHA256 does not match the bound model")
if runtime_instance.payload["executable_sha256"] != llama_sha256:
    raise SystemExit("Runtime-instance executable SHA256 does not match llama-server")
context = None
if context_selection_text:
    context = json.loads(Path(context_selection_text).read_text(encoding="utf-8"))
if context_proof_text:
    context = json.loads(Path(context_proof_text).read_text(encoding="utf-8"))
if any(report.get("run_id") != run_id for report in (retrieval, quality, stress, benchmark)):
    raise SystemExit("Retrieval, quality, stress and benchmark reports must match the run-id")
if quality.get("passed") is not True or benchmark.get("quality_gate", {}).get("passed") is not True:
    raise SystemExit("Quality and benchmark release gates must both pass")
if not (
    quality.get("metrics", {}).get("total_score") == 300
    and quality.get("metrics", {}).get("maximum_score") == 300
    and all(value is True for value in quality.get("gates", {}).values())
):
    raise SystemExit("Agent quality must prove 300/300 and every release gate")
try:
    validate_stress_report(stress, "collector")
except ValueError as exc:
    raise SystemExit(str(exc)) from exc
if benchmark.get("schema_version") != 3:
    raise SystemExit("Benchmark report must use schema_version 3")
if benchmark.get("quality_report", {}).get("sha256") != quality_sha256:
    raise SystemExit("Benchmark is not bound to the supplied quality report")
if not (
    retrieval.get("suite_version")
    == quality.get("suite_version")
    == benchmark.get("suite_version")
    == "30-case-p0-v3"
):
    raise SystemExit("Retrieval, quality and benchmark suite versions differ")
if not (
    retrieval.get("suite_sha256")
    == quality.get("suite_sha256")
    == benchmark.get("suite_sha256")
    == "60fae4be0bd7a16ee9b2e7963bb3afccbf319c2ed64cd3ba43acfc912bfd3d1b"
):
    raise SystemExit("Retrieval, quality and benchmark must use the official suite hash")
if retrieval.get("quality_gate", {}).get("passed") is not True:
    raise SystemExit("Retrieval release gate must pass")
policy_root = validate_policy_directory(
    project / "data" / "policies",
    project_root=project,
)
policy_sha256 = policy_corpus_sha256(policy_root, project_root=project)
if not (
    retrieval.get("policy_corpus_sha256")
    == quality.get("policy_corpus_sha256")
    == stress.get("policy_corpus_sha256")
    == benchmark.get("policy_corpus_sha256")
    == policy_sha256
):
    raise SystemExit("Retrieval, quality and benchmark policy corpus hashes mismatch")
if quality.get("model", {}).get("name") != benchmark.get("model_name"):
    raise SystemExit("Quality and benchmark model aliases differ")
if stress.get("model", {}).get("name") != quality.get("model", {}).get("name"):
    raise SystemExit("Stress and quality model aliases differ")
for report, label in ((quality, "quality"), (benchmark, "benchmark")):
    artifacts = report.get("artifacts", {})
    if artifacts.get("model_file_sha256") != model_sha256:
        raise SystemExit(f"{label} report model hash mismatch")
    if artifacts.get("llama_server_sha256") != llama_sha256:
        raise SystemExit(f"{label} report llama-server hash mismatch")
if stress.get("artifacts") != quality.get("artifacts"):
    raise SystemExit("Stress and quality artifact bindings differ")
if stress.get("request_configuration") != quality.get("request_configuration"):
    raise SystemExit("Stress and quality request configurations differ")
if stress.get("service_configuration") != quality.get("service_configuration"):
    raise SystemExit("Stress and quality service configurations differ")
if stress.get("policy_corpus_sha256") != quality.get("policy_corpus_sha256"):
    raise SystemExit("Stress and quality policy corpus hashes differ")
for report, report_kind, label in (
    (quality, "quality", "quality"),
    (stress, "quality", "stress"),
    (benchmark, "benchmark", "benchmark"),
):
    try:
        validate_report_runtime_binding(
            report,
            expected_manifest_sha256=runtime_instance.manifest_sha256,
            report_kind=report_kind,
            label=f"collector {label}",
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
experiment = quality.get("service_configuration", {}).get("experiment")
if experiment == "E" and (not context_selection_text or context_proof_text):
    raise SystemExit("Run E requires exactly one context selection artifact")
if experiment == "F" and (context_selection_text or not context_proof_text):
    raise SystemExit("Run F requires exactly one context proof artifact")
if experiment not in {"E", "F"} and (context_selection_text or context_proof_text):
    raise SystemExit("Only runs E and F may bind context evidence")
try:
    validate_context_evidence(
        context,
        quality,
        benchmark,
        "collector",
        quality_sha256=quality_sha256,
        benchmark_sha256=benchmark_sha256,
    )
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

source_sha256 = source_tree_sha256(project)
for report, label in (
    (retrieval, "retrieval"),
    (quality, "quality"),
    (stress, "stress"),
    (benchmark, "benchmark"),
):
    provenance = report.get("provenance", {})
    expected = {
        "commit": commit,
        "project_tree": project_tree,
        "source_tree_sha256": source_sha256,
    }
    for field, value in expected.items():
        if provenance.get(field) != value:
            raise SystemExit(f"{label} report provenance mismatch: {field}")

def values(path: Path) -> dict[str, str]:
    parsed = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in raw_line:
            key, value = raw_line.split("=", 1)
            if key and key not in parsed:
                parsed[key] = value
    return parsed

def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def sample_rows(path: Path) -> list[tuple[int, str, datetime]]:
    rows = []
    pattern = re.compile(
        r"sample=([1-9][0-9]*) run_id=(\S+) collected_at_utc=(\S+)"
    )
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.startswith("sample="):
            continue
        match = pattern.fullmatch(raw_line)
        if match is None:
            raise SystemExit("Monitor evidence contains a malformed sample line")
        rows.append((int(match.group(1)), match.group(2), instant(match.group(3))))
    return rows

monitor = values(Path(monitor_text))
server = values(Path(server_text))
if monitor.get("run_id") != run_id or monitor.get("status") != "complete":
    raise SystemExit("Monitor evidence is incomplete or has the wrong run-id")
if monitor.get("schema_version") != "1":
    raise SystemExit("Monitor evidence must use schema_version 1")
if server.get("evidence_run_id") != run_id or server.get("evidence_log_status") != "complete":
    raise SystemExit("Server evidence is incomplete or has the wrong run-id")
if server.get("llama_server_exit_code") not in {"0", "143"}:
    raise SystemExit("Server evidence contains a failed llama-server exit code")
if server.get("model_sha256_at_start") != model_sha256:
    raise SystemExit("Model hash changed or does not match the server startup evidence")
if server.get("llama_server_sha256_at_start") != llama_sha256:
    raise SystemExit("llama-server hash changed or does not match startup evidence")
if not (
    server.get("runtime_instance_manifest_sha256")
    == runtime_instance.manifest_sha256
    and server.get("process_binding_valid") == "true"
    and server.get("listen_socket_binding_valid") == "true"
):
    raise SystemExit("Server log lacks the bound PID/LISTEN socket attestation")
quality_model = quality.get("model")
if not isinstance(quality_model, dict):
    raise SystemExit("Quality report has invalid model metadata")
if not (
    server.get("model_alias")
    == quality_model.get("name")
    == benchmark.get("model_name")
):
    raise SystemExit("Server, quality and benchmark model aliases differ")
if not (
    server.get("model_base_url")
    == quality_model.get("base_url")
    == benchmark.get("model_base_url")
):
    raise SystemExit("Server, quality and benchmark model endpoints differ")
try:
    monitor_interval = float(monitor["interval_seconds"])
    completed_samples = int(monitor["completed_samples"])
except (KeyError, TypeError, ValueError) as exc:
    raise SystemExit("Monitor evidence has invalid interval or sample metadata") from exc
if not 0 < monitor_interval <= 5:
    raise SystemExit("Monitor interval must be greater than zero and at most 5 seconds")
samples = sample_rows(Path(monitor_text))
if completed_samples != len(samples) or completed_samples < 2:
    raise SystemExit("Monitor sample count is incomplete or inconsistent")
maximum_gap_seconds = max(5.0, monitor_interval * 3.0)
for expected_sequence, (sequence, sample_run_id, collected_at) in enumerate(samples, 1):
    if sequence != expected_sequence:
        raise SystemExit("Monitor sample sequence is not contiguous")
    if sample_run_id != run_id:
        raise SystemExit("Monitor sample has the wrong run-id")
    if expected_sequence == 1:
        continue
    previous_time = samples[expected_sequence - 2][2]
    if collected_at < previous_time:
        raise SystemExit("Monitor sample timestamps are not monotonic")
    if (collected_at - previous_time).total_seconds() > maximum_gap_seconds:
        raise SystemExit("Monitor evidence contains an excessive sampling gap")
monitor_start = instant(monitor["started_at_utc"])
monitor_end = instant(monitor["completed_at_utc"])
server_start = instant(server["server_started_at_utc"])
server_end = instant(server["server_completed_at_utc"])
quality_start = instant(quality["started_at_utc"])
quality_end = instant(quality["completed_at_utc"])
stress_start = instant(stress["started_at_utc"])
stress_end = instant(stress["completed_at_utc"])
benchmark_start = instant(benchmark["started_at_utc"])
benchmark_end = instant(benchmark["completed_at_utc"])
retrieval_start = instant(retrieval["started_at_utc"])
retrieval_end = instant(retrieval["completed_at_utc"])
if not (
    server_start
    <= retrieval_start
    <= retrieval_end
    <= quality_start
    <= quality_end
    <= stress_start
    <= stress_end
    <= benchmark_start
    <= benchmark_end
    <= server_end
):
    raise SystemExit("Server log does not cover the ordered evaluation windows")
first_sample_at = samples[0][2]
last_sample_at = samples[-1][2]
if not (monitor_start <= first_sample_at <= last_sample_at <= monitor_end):
    raise SystemExit("ROCm monitor sample timestamps exceed the declared window")
if not (first_sample_at <= retrieval_start and benchmark_end <= last_sample_at):
    raise SystemExit("ROCm monitor samples do not cover all evaluation windows")
try:
    runtime_gpu_summary(
        Path(server_text),
        Path(monitor_text),
        "collector",
        required_windows={
            "agent_quality": (quality_start, quality_end),
            "stress": (stress_start, stress_end),
            "agent_benchmark": (benchmark_start, benchmark_end),
        },
        expected_run_id=run_id,
        expected_sample_count=completed_samples,
        maximum_sample_gap_seconds=maximum_gap_seconds,
        coverage_window=(retrieval_start, benchmark_end),
        declared_monitor_window=(monitor_start, monitor_end),
        require_device_identity=True,
    )
except ValueError as exc:
    raise SystemExit(str(exc)) from exc
print(source_sha256)
PY
)"

if [[ "$(sha256sum -- "${model_file}" | awk '{print $1}')" != "${model_sha256}" \
      || "$(sha256sum -- "${llama_server}" | awk '{print $1}')" != "${llama_server_sha256}" \
      || "$(sha256sum -- "${requirements_lock}" | awk '{print $1}')" != "${requirements_lock_sha256}" \
      || "$(sha256sum -- "${runtime_instance_file}" | awk '{print $1}')" != "${runtime_instance_sha256}" \
      || "$(sha256sum -- "${live_evidence_file}" | awk '{print $1}')" != "${live_rocm_sha256}" ]]; then
  echo "Bound model, process manifest, dependency lock, or live evidence changed" >&2
  exit 3
fi
if [[ -n "${context_selection_file}" \
      && "$(sha256sum -- "${context_selection_file}" | awk '{print $1}')" != "${context_selection_sha256}" ]]; then
  echo "Context selection evidence changed during collection" >&2
  exit 3
fi
if [[ -n "${context_proof_file}" \
      && "$(sha256sum -- "${context_proof_file}" | awk '{print $1}')" != "${context_proof_sha256}" ]]; then
  echo "Context proof evidence changed during collection" >&2
  exit 3
fi

mkdir -m 0700 -- "${output_dir}"
cp -- "${retrieval_file}" "${output_dir}/retrieval.json"
cp -- "${quality_file}" "${output_dir}/agent-quality.json"
cp -- "${stress_file}" "${output_dir}/stress.json"
if [[ -n "${context_selection_file}" ]]; then
  cp -- "${context_selection_file}" "${output_dir}/context-selection.json"
fi
if [[ -n "${context_proof_file}" ]]; then
  cp -- "${context_proof_file}" "${output_dir}/context-proof.json"
fi
cp -- "${benchmark_file}" "${output_dir}/agent-benchmark.json"
cp -- "${monitor_file}" "${output_dir}/rocm-monitor.log"
cp -- "${server_log}" "${output_dir}/llama-server.log"
cp -- "${runtime_instance_file}" "${output_dir}/runtime-instance.json"
cp -- "${live_evidence_file}" "${output_dir}/live-rocm.log"

{
  echo "collected_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "collector=collect_rocm_evidence.sh"
  echo "run_id=${run_id}"
  echo "project_dir=${project_dir}"
  echo "repository_root=${repository_root}"
  echo "project_prefix=${project_prefix}"
  echo "commit=${commit}"
  echo "project_tree=${project_tree}"
  echo "source_tree_sha256=${source_tree_sha256}"
  echo "python_executable=${python_executable_path}"
  echo "python_version=${python_version}"
  echo "requirements_lock_sha256=${requirements_lock_sha256}"
  echo "working_directory=$(pwd -P)"
} > "${output_dir}/manifest.txt"

{
  uname -a
  echo
  if [[ -r /etc/os-release ]]; then
    sed -n '1,120p' /etc/os-release
  else
    echo "/etc/os-release is unavailable"
  fi
  echo
  if command -v lscpu >/dev/null 2>&1; then
    LC_ALL=C lscpu
  else
    echo "lscpu is unavailable"
  fi
} > "${output_dir}/system.txt" 2>&1

LC_ALL=C rocminfo > "${output_dir}/rocminfo.txt" 2>&1
LC_ALL=C rocm-smi > "${output_dir}/rocm-smi.txt" 2>&1

{
  if [[ -r /opt/rocm/.info/version ]]; then
    echo "rocm_version=$(sed -n '1p' /opt/rocm/.info/version)"
  else
    echo "rocm_version_file=/opt/rocm/.info/version unavailable"
  fi
  if command -v hipconfig >/dev/null 2>&1; then
    LC_ALL=C hipconfig --version
  else
    echo "hipconfig is unavailable"
  fi
} > "${output_dir}/rocm-version.txt" 2>&1

{
  git --version
  echo "repository_root=${repository_root}"
  echo "project_dir=${project_dir}"
  echo "project_prefix=${project_prefix}"
  echo "commit=${commit}"
  echo "project_tree=${project_tree}"
  echo "source_tree_sha256=${source_tree_sha256}"
  echo "branch=$(git -C "${project_dir}" branch --show-current)"
  echo "describe=$(git -C "${project_dir}" describe --always --dirty --tags)"
  echo
  git -C "${project_dir}" status --short --branch
} > "${output_dir}/git.txt" 2>&1

{
  stable_system_sha256="$(
    LC_ALL=C grep -Ev \
      '^[[:space:]]*(CPU MHz|CPU\(s\) scaling MHz):' \
      "${output_dir}/system.txt" | sha256sum | awk '{print $1}'
  )"
  hardware_identity_sha256="$({
    echo "${stable_system_sha256}"
    for identity_file in \
      "${output_dir}/rocminfo.txt" \
      "${output_dir}/rocm-version.txt"; do
      sha256sum -- "${identity_file}" | awk '{print $1}'
    done
  } | sha256sum | awk '{print $1}')"
  echo "schema_version=3"
  echo "run_id=${run_id}"
  echo "created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "binding_status=complete"
  echo "commit=${commit}"
  echo "project_tree=${project_tree}"
  echo "source_tree_sha256=${source_tree_sha256}"
  echo "hardware_identity_algorithm=stable-system-v1+rocminfo+rocm-version"
  echo "hardware_identity_sha256=${hardware_identity_sha256}"
  echo "retrieval_file=retrieval.json"
  echo "retrieval_sha256=${retrieval_sha256}"
  echo "quality_file=agent-quality.json"
  echo "quality_sha256=${quality_sha256}"
  echo "stress_file=stress.json"
  echo "stress_sha256=${stress_sha256}"
  if [[ -n "${context_selection_file}" ]]; then
    echo "context_selection_file=context-selection.json"
    echo "context_selection_sha256=${context_selection_sha256}"
  fi
  if [[ -n "${context_proof_file}" ]]; then
    echo "context_proof_file=context-proof.json"
    echo "context_proof_sha256=${context_proof_sha256}"
  fi
  echo "benchmark_file=agent-benchmark.json"
  echo "benchmark_sha256=${benchmark_sha256}"
  echo "monitor_file=rocm-monitor.log"
  echo "monitor_sha256=${monitor_sha256}"
  echo "server_log=llama-server.log"
  echo "server_log_sha256=${server_log_sha256}"
  echo "runtime_instance_file=runtime-instance.json"
  echo "runtime_instance_sha256=${runtime_instance_sha256}"
  echo "model_file=${model_file}"
  echo "expected_model_sha256=${expected_model_sha256}"
  echo "model_sha256=${model_sha256}"
  echo "model_repository=${model_repository}"
  echo "model_revision=${model_revision}"
  echo "model_license=${model_license}"
  echo "model_quantization=${model_quantization}"
  echo "llama_server=${llama_server}"
  echo "expected_llama_server_sha256=${expected_llama_server_sha256}"
  echo "llama_server_sha256=${llama_server_sha256}"
  echo "llama_cpp_commit=${llama_cpp_commit}"
  echo "llama_build=${llama_build}"
  echo "python_executable=${python_executable_path}"
  echo "python_version=${python_version}"
  echo "requirements_lock_file=requirements.lock"
  echo "requirements_lock_sha256=${requirements_lock_sha256}"
  echo "live_rocm_file=live-rocm.log"
  echo "live_rocm_sha256=${live_rocm_sha256}"
} > "${output_dir}/binding-manifest.txt"

(
  cd -- "${output_dir}"
  checksum_files=(
    manifest.txt system.txt rocminfo.txt rocm-smi.txt rocm-version.txt git.txt
    retrieval.json agent-quality.json stress.json agent-benchmark.json
    rocm-monitor.log llama-server.log live-rocm.log binding-manifest.txt
    runtime-instance.json
  )
  if [[ -n "${context_selection_file}" ]]; then
    checksum_files+=(context-selection.json)
  fi
  if [[ -n "${context_proof_file}" ]]; then
    checksum_files+=(context-proof.json)
  fi
  sha256sum "${checksum_files[@]}"
) > "${output_dir}/SHA256SUMS.txt"

echo "ROCm evidence for run ${run_id} written to new directory: ${output_dir}"
