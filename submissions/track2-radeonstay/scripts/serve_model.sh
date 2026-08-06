#!/usr/bin/env bash
set -euo pipefail

: "${LLAMA_SERVER:?Set LLAMA_SERVER to the ROCm-enabled llama-server binary}"
: "${MODEL_PATH:?Set MODEL_PATH to the pinned local GGUF file}"

MODEL_ALIAS="${MODEL_ALIAS:-qwen3.6-35b-a3b-q6k}"
MODEL_HOST="${MODEL_HOST:-127.0.0.1}"
MODEL_PORT="${MODEL_PORT:-8000}"
CONTEXT_SIZE="${CONTEXT_SIZE:-16384}"
PARALLEL_SLOTS="${PARALLEL_SLOTS:-1}"
BATCH_SIZE="${BATCH_SIZE:-512}"
UBATCH_SIZE="${UBATCH_SIZE:-128}"
FLASH_ATTN="${FLASH_ATTN:-auto}"
GPU_LAYERS="${GPU_LAYERS:-999}"
CACHE_TYPE_K="${CACHE_TYPE_K:-f16}"
CACHE_TYPE_V="${CACHE_TYPE_V:-f16}"
EVIDENCE_RUN_ID="${EVIDENCE_RUN_ID:-}"
RUNTIME_INSTANCE_PATH="${RADEONSTAY_RUNTIME_INSTANCE_PATH:-}"
RUNTIME_INSTANCE_RUN_ID="${RADEONSTAY_DEMO_RUN_ID:-${EVIDENCE_RUN_ID}}"
EXPECTED_SERVICE_CONFIGURATION_SHA256="${EXPECTED_SERVICE_CONFIGURATION_SHA256:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_VERBOSITY="5"

for evidence_path in "${LLAMA_SERVER}" "${MODEL_PATH}"; do
  if [[ "${evidence_path}" == *$'\n'* || "${evidence_path}" == *$'\r'* ]]; then
    echo "LLAMA_SERVER and MODEL_PATH must not contain CR or LF characters" >&2
    exit 2
  fi
done
if [[ ! -x "${LLAMA_SERVER}" ]]; then
  echo "llama-server is not executable: ${LLAMA_SERVER}" >&2
  exit 1
fi
if [[ ! -f "${MODEL_PATH}" ]]; then
  echo "model file does not exist: ${MODEL_PATH}" >&2
  exit 1
fi
LLAMA_SERVER="$(cd -- "$(dirname -- "${LLAMA_SERVER}")" && pwd -P)/$(basename -- "${LLAMA_SERVER}")"
MODEL_PATH="$(cd -- "$(dirname -- "${MODEL_PATH}")" && pwd -P)/$(basename -- "${MODEL_PATH}")"
for evidence_path in "${LLAMA_SERVER}" "${MODEL_PATH}"; do
  if [[ "${evidence_path}" == *$'\n'* || "${evidence_path}" == *$'\r'* ]]; then
    echo "Resolved LLAMA_SERVER and MODEL_PATH must not contain CR or LF characters" >&2
    exit 2
  fi
done
if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum is required for evidence-bound model startup" >&2
  exit 2
fi
MODEL_SHA256="$(sha256sum -- "${MODEL_PATH}" | awk '{print $1}')"
LLAMA_SERVER_SHA256="$(sha256sum -- "${LLAMA_SERVER}" | awk '{print $1}')"
case "${MODEL_HOST}" in
  127.0.0.1|localhost|::1) ;;
  *)
    echo "MODEL_HOST must be a loopback address for the competition path" >&2
    exit 2
    ;;
esac
case "${FLASH_ATTN}" in
  auto|on|off) ;;
  *)
    echo "FLASH_ATTN must be auto, on, or off" >&2
    exit 2
    ;;
esac
case "${CACHE_TYPE_K}" in
  f16|q8_0) ;;
  *)
    echo "CACHE_TYPE_K must be f16 or q8_0" >&2
    exit 2
    ;;
esac
case "${CACHE_TYPE_V}" in
  f16|q8_0) ;;
  *)
    echo "CACHE_TYPE_V must be f16 or q8_0" >&2
    exit 2
    ;;
esac
if [[ -n "${EVIDENCE_RUN_ID}" \
      && ! "${EVIDENCE_RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$ ]]; then
  echo "EVIDENCE_RUN_ID has an invalid format" >&2
  exit 2
fi
if [[ -n "${RUNTIME_INSTANCE_PATH}" ]]; then
  if [[ "${RUNTIME_INSTANCE_PATH}" == *$'\n'* \
        || "${RUNTIME_INSTANCE_PATH}" == *$'\r'* ]]; then
    echo "RADEONSTAY_RUNTIME_INSTANCE_PATH must not contain CR or LF" >&2
    exit 2
  fi
  if [[ ! "${RUNTIME_INSTANCE_RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$ ]]; then
    echo "A valid demo or evidence run ID is required for process binding" >&2
    exit 2
  fi
  for required_command in readlink stat "${PYTHON_BIN}"; do
    if ! command -v "${required_command}" >/dev/null 2>&1; then
      echo "${required_command} is required for process-bound startup" >&2
      exit 2
    fi
  done
fi
if [[ ! "${MODEL_ALIAS}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]; then
  echo "MODEL_ALIAS has an invalid evidence format" >&2
  exit 2
fi
if [[ ! "${CONTEXT_SIZE}" =~ ^[1-9][0-9]{0,8}$ \
      || ! "${PARALLEL_SLOTS}" =~ ^[1-9][0-9]{0,3}$ \
      || ! "${BATCH_SIZE}" =~ ^[1-9][0-9]{0,8}$ \
      || ! "${UBATCH_SIZE}" =~ ^[1-9][0-9]{0,8}$ \
      || ! "${GPU_LAYERS}" =~ ^[1-9][0-9]{0,5}$ ]]; then
  echo "Context, parallel, batch, ubatch, and GPU layers must be positive integers" >&2
  exit 2
fi
if [[ ! "${MODEL_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] \
    || (( MODEL_PORT > 65535 )); then
  echo "MODEL_PORT must be an integer between 1 and 65535" >&2
  exit 2
fi
if [[ -n "${EXPECTED_SERVICE_CONFIGURATION_SHA256}" \
      && ! "${EXPECTED_SERVICE_CONFIGURATION_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "EXPECTED_SERVICE_CONFIGURATION_SHA256 must be a lowercase SHA256" >&2
  exit 2
fi
if [[ "${MODEL_HOST}" == "::1" ]]; then
  MODEL_BASE_URL="http://[::1]:${MODEL_PORT}/v1"
else
  MODEL_BASE_URL="http://${MODEL_HOST}:${MODEL_PORT}/v1"
fi

args=(
  --model "${MODEL_PATH}"
  --alias "${MODEL_ALIAS}"
  --host "${MODEL_HOST}"
  --port "${MODEL_PORT}"
  --n-gpu-layers "${GPU_LAYERS}"
  --ctx-size "${CONTEXT_SIZE}"
  --parallel "${PARALLEL_SLOTS}"
  --batch-size "${BATCH_SIZE}"
  --ubatch-size "${UBATCH_SIZE}"
)

help_text="$("${LLAMA_SERVER}" --help 2>&1 || true)"
EFFECTIVE_FLASH_ATTN="off"
if grep -q -- '--log-verbosity' <<<"${help_text}"; then
  args+=(--log-verbosity "${LOG_VERBOSITY}")
else
  echo "This llama-server build does not expose required --log-verbosity" >&2
  exit 2
fi
if grep -q -- '--flash-attn' <<<"${help_text}"; then
  case "${FLASH_ATTN}" in
    auto|on) args+=(--flash-attn on); EFFECTIVE_FLASH_ATTN="on" ;;
    off) args+=(--flash-attn off); EFFECTIVE_FLASH_ATTN="off" ;;
  esac
elif [[ "${FLASH_ATTN}" == "on" ]]; then
  echo "This llama-server build does not expose --flash-attn" >&2
  exit 2
fi
if grep -q -- '--cache-type-k' <<<"${help_text}" \
    && grep -q -- '--cache-type-v' <<<"${help_text}"; then
  args+=(--cache-type-k "${CACHE_TYPE_K}" --cache-type-v "${CACHE_TYPE_V}")
elif [[ "${CACHE_TYPE_K}" != "f16" || "${CACHE_TYPE_V}" != "f16" ]]; then
  echo "This llama-server build does not expose KV cache type controls" >&2
  exit 2
fi
if grep -q -- '--jinja' <<<"${help_text}"; then
  args+=(--jinja)
fi
if grep -q -- '--metrics' <<<"${help_text}"; then
  args+=(--metrics)
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "PYTHON_BIN is required to bind the effective service configuration" >&2
  exit 2
fi
SERVICE_CONFIGURATION_SHA256="$(
  "${PYTHON_BIN}" - \
    "${CONTEXT_SIZE}" "${PARALLEL_SLOTS}" "${BATCH_SIZE}" \
    "${UBATCH_SIZE}" "${EFFECTIVE_FLASH_ATTN}" "${GPU_LAYERS}" \
    "${CACHE_TYPE_K}" "${CACHE_TYPE_V}" "${LOG_VERBOSITY}" <<'PY_CONFIG_SHA'
import hashlib
import json
import sys

(
    ctx,
    parallel,
    batch,
    ubatch,
    flash_attn,
    gpu_layers,
    cache_type_k,
    cache_type_v,
    log_verbosity,
) = sys.argv[1:]
configuration = {
    "ctx": int(ctx),
    "parallel": int(parallel),
    "batch": int(batch),
    "ubatch": int(ubatch),
    "flash_attn": flash_attn,
    "gpu_layers": int(gpu_layers),
    "cache_type_k": cache_type_k,
    "cache_type_v": cache_type_v,
    "log_verbosity": int(log_verbosity),
}
canonical = json.dumps(
    configuration,
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("ascii")
print(hashlib.sha256(canonical).hexdigest())
PY_CONFIG_SHA
)"
if [[ -n "${EXPECTED_SERVICE_CONFIGURATION_SHA256}" \
      && "${SERVICE_CONFIGURATION_SHA256}" != "${EXPECTED_SERVICE_CONFIGURATION_SHA256}" ]]; then
  echo "Effective service configuration differs from the accepted release profile" >&2
  exit 2
fi

echo "Starting local ROCm model ${MODEL_ALIAS} on ${MODEL_HOST}:${MODEL_PORT}"
echo "evidence_run_id=${EVIDENCE_RUN_ID:-unbound}"
echo "model_alias=${MODEL_ALIAS}"
echo "model_base_url=${MODEL_BASE_URL}"
echo "launcher_pid=$$"
echo "llama_server_path=${LLAMA_SERVER}"
echo "llama_server_sha256_at_start=${LLAMA_SERVER_SHA256}"
echo "model_path=${MODEL_PATH}"
echo "model_sha256_at_start=${MODEL_SHA256}"
echo "ctx=${CONTEXT_SIZE} parallel=${PARALLEL_SLOTS}"
echo "batch=${BATCH_SIZE} ubatch=${UBATCH_SIZE} flash_attn=${FLASH_ATTN}"
echo "gpu_layers=${GPU_LAYERS}"
echo "cache_type_k=${CACHE_TYPE_K} cache_type_v=${CACHE_TYPE_V}"
echo "log_verbosity=${LOG_VERBOSITY}"
echo "service_configuration_sha256=${SERVICE_CONFIGURATION_SHA256}"
echo "server_started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

server_pid=""
controlled_term=0
forward_signal() {
  local signal_name="$1"
  if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
    kill -s "${signal_name}" "${server_pid}" 2>/dev/null || true
  fi
}
handle_term() {
  controlled_term=1
  forward_signal TERM
}
cleanup_started_server() {
  local status=$?
  if [[ "${status}" -ne 0 \
        && -n "${server_pid}" \
        && "${controlled_term}" -eq 0 ]] \
      && kill -0 "${server_pid}" 2>/dev/null; then
    kill -s TERM "${server_pid}" 2>/dev/null || true
    wait "${server_pid}" 2>/dev/null || true
  fi
}
trap 'handle_term' TERM
trap 'forward_signal INT' INT
trap 'cleanup_started_server' EXIT

"${LLAMA_SERVER}" "${args[@]}" &
server_pid=$!
echo "llama_server_pid=${server_pid}"

if [[ -n "${RUNTIME_INSTANCE_PATH}" ]]; then
  instance_parent="$(dirname -- "${RUNTIME_INSTANCE_PATH}")"
  if [[ ! -d "${instance_parent}" \
        || -L "${instance_parent}" \
        || "$(stat -c '%a' -- "${instance_parent}")" != "700" \
        || -e "${RUNTIME_INSTANCE_PATH}" \
        || -L "${RUNTIME_INSTANCE_PATH}" ]]; then
    echo "Runtime instance path must be new inside a private 0700 directory" >&2
    handle_term
    wait "${server_pid}" 2>/dev/null || true
    exit 2
  fi

  observed_executable=""
  for _ in {1..200}; do
    if ! kill -0 "${server_pid}" 2>/dev/null; then
      break
    fi
    observed_executable="$(readlink -f -- "/proc/${server_pid}/exe" 2>/dev/null || true)"
    if [[ "${observed_executable}" == "${LLAMA_SERVER}" ]]; then
      break
    fi
    sleep 0.05
  done
  if [[ "${observed_executable}" != "${LLAMA_SERVER}" ]]; then
    echo "llama-server did not establish the expected Linux process identity" >&2
    handle_term
    wait "${server_pid}" 2>/dev/null || true
    exit 2
  fi

  linux_start_ticks="$(awk '{print $22}' "/proc/${server_pid}/stat")"
  process_executable_sha256="$(
    sha256sum -- "/proc/${server_pid}/exe" | awk '{print $1}'
  )"
  command_config_sha256="$(
    sha256sum -- "/proc/${server_pid}/cmdline" | awk '{print $1}'
  )"
  if [[ ! "${linux_start_ticks}" =~ ^[1-9][0-9]*$ \
        || "${process_executable_sha256}" != "${LLAMA_SERVER_SHA256}" ]]; then
    echo "llama-server process evidence did not match the pinned executable" >&2
    handle_term
    wait "${server_pid}" 2>/dev/null || true
    exit 2
  fi

  instance_tmp="${RUNTIME_INSTANCE_PATH}.tmp.$$"
  umask 077
  if [[ -e "${instance_tmp}" || -L "${instance_tmp}" ]]; then
    echo "Runtime instance temporary path already exists" >&2
    handle_term
    wait "${server_pid}" 2>/dev/null || true
    exit 2
  fi
  printf '%s\n' \
    '{' \
    '  "schema_version": 2,' \
    "  \"run_id\": \"${RUNTIME_INSTANCE_RUN_ID}\"," \
    "  \"pid\": ${server_pid}," \
    "  \"linux_start_ticks\": ${linux_start_ticks}," \
    "  \"executable_sha256\": \"${process_executable_sha256}\"," \
    "  \"command_config_sha256\": \"${command_config_sha256}\"," \
    "  \"service_configuration_sha256\": \"${SERVICE_CONFIGURATION_SHA256}\"," \
    "  \"port\": ${MODEL_PORT}," \
    "  \"model_alias\": \"${MODEL_ALIAS}\"," \
    "  \"model_sha256\": \"${MODEL_SHA256}\"" \
    '}' >"${instance_tmp}"
  chmod 0600 -- "${instance_tmp}"
  if ! "${PYTHON_BIN}" \
      "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)/evaluation/runtime_binding_evidence.py" \
      --manifest "${instance_tmp}" \
      --run-id "${RUNTIME_INSTANCE_RUN_ID}" \
      --verify-listener \
      --timeout-seconds 120 >/dev/null; then
    unlink -- "${instance_tmp}" 2>/dev/null || true
    echo "llama-server did not own the declared loopback LISTEN socket" >&2
    handle_term
    wait "${server_pid}" 2>/dev/null || true
    exit 2
  fi
  if ! ln -- "${instance_tmp}" "${RUNTIME_INSTANCE_PATH}"; then
    unlink -- "${instance_tmp}" 2>/dev/null || true
    echo "Refusing to overwrite an existing runtime instance manifest" >&2
    handle_term
    wait "${server_pid}" 2>/dev/null || true
    exit 2
  fi
  unlink -- "${instance_tmp}"
  runtime_instance_sha256="$(
    sha256sum -- "${RUNTIME_INSTANCE_PATH}" | awk '{print $1}'
  )"
  echo "runtime_instance_manifest_sha256=${runtime_instance_sha256}"
  echo "process_binding_valid=true"
  echo "listen_socket_binding_valid=true"
fi

set +e
wait "${server_pid}"
server_status=$?
while kill -0 "${server_pid}" 2>/dev/null; do
  wait "${server_pid}"
  server_status=$?
done
set -e

echo "server_completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "llama_server_exit_code=${server_status}"
if [[ "${server_status}" -eq 0 \
      || ( "${server_status}" -eq 143 && "${controlled_term}" -eq 1 ) ]]; then
  echo "evidence_log_status=complete"
else
  echo "evidence_log_status=failed"
fi
exit "${server_status}"
