#!/usr/bin/env bash
set -euo pipefail
set -C

usage() {
  echo "Usage: $0 --run-id RUN_ID --output NEW_FILE [--interval SECONDS] [--samples COUNT] [--stop-file NEW_FILE]" >&2
}

run_id=""
output_file=""
interval="1"
samples="300"
stop_file=""
while [[ $# -gt 0 ]]; do
  if [[ $# -lt 2 ]]; then
    usage
    exit 2
  fi
  case "$1" in
    --run-id)
      run_id="${2:-}"
      shift 2
      ;;
    --output)
      output_file="${2:-}"
      shift 2
      ;;
    --interval)
      interval="${2:-}"
      shift 2
      ;;
    --samples)
      samples="${2:-}"
      shift 2
      ;;
    --stop-file)
      stop_file="${2:-}"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

for evidence_path in "${output_file}" "${stop_file}"; do
  if [[ "${evidence_path}" == *$'\n'* || "${evidence_path}" == *$'\r'* ]]; then
    echo "Monitor paths must not contain CR or LF characters" >&2
    exit 3
  fi
done
if [[ ! "${run_id}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$ ]]; then
  echo "Run ID must be 1-48 characters using letters, digits, dot, underscore, colon, or hyphen" >&2
  exit 3
fi
if [[ -z "${output_file}" || -e "${output_file}" ]]; then
  echo "Output must be a new file: ${output_file:-<empty>}" >&2
  exit 3
fi
if [[ ! "${interval}" =~ ^[1-9][0-9]*([.][0-9]+)?$ \
      && ! "${interval}" =~ ^0[.][0-9]*[1-9][0-9]*$ ]]; then
  echo "Interval must be a positive number" >&2
  exit 3
fi
if [[ ! "${samples}" =~ ^[1-9][0-9]*$ ]] || (( samples > 86400 )); then
  echo "Samples must be an integer between 1 and 86400" >&2
  exit 3
fi
if [[ ! -d "$(dirname -- "${output_file}")" ]]; then
  echo "Output parent directory does not exist" >&2
  exit 3
fi
if [[ -n "${stop_file}" ]]; then
  if [[ -e "${stop_file}" || ! -d "$(dirname -- "${stop_file}")" ]]; then
    echo "Stop file must not exist and its parent directory must exist" >&2
    exit 3
  fi
fi
output_file="$(cd -- "$(dirname -- "${output_file}")" && pwd -P)/$(basename -- "${output_file}")"
if [[ -n "${stop_file}" ]]; then
  stop_file="$(cd -- "$(dirname -- "${stop_file}")" && pwd -P)/$(basename -- "${stop_file}")"
fi
for evidence_path in "${output_file}" "${stop_file}"; do
  if [[ "${evidence_path}" == *$'\n'* || "${evidence_path}" == *$'\r'* ]]; then
    echo "Resolved monitor paths must not contain CR or LF characters" >&2
    exit 3
  fi
done
if ! command -v rocm-smi >/dev/null 2>&1; then
  echo "rocm-smi is required" >&2
  exit 4
fi

: > "${output_file}"

{
  echo "schema_version=1"
  echo "collector=monitor_rocm.sh"
  echo "run_id=${run_id}"
  echo "started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "interval_seconds=${interval}"
  echo "requested_samples=${samples}"
  echo "stop_file=${stop_file:-not_configured}"
  echo "device_identity_begin"
  LC_ALL=C rocm-smi --showproductname --showserial --showuniqueid
  echo "device_identity_end"
} >> "${output_file}"

completed_samples=0
stop_reason="max_samples"
for ((index = 1; index <= samples; index++)); do
  {
    echo "sample=${index} run_id=${run_id} collected_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    LC_ALL=C rocm-smi --showuse --showmemuse --showmeminfo vram --showpower --showtemp
    echo
  } >> "${output_file}"
  completed_samples="${index}"
  if [[ -n "${stop_file}" && -e "${stop_file}" ]]; then
    stop_reason="stop_file"
    break
  fi
  if (( index < samples )); then
    sleep "${interval}"
  fi
done

{
  echo "completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "completed_samples=${completed_samples}"
  echo "stop_reason=${stop_reason}"
  echo "status=complete"
} >> "${output_file}"

echo "ROCm monitoring evidence for run ${run_id} written to: ${output_file}"
