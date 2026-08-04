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
EVIDENCE_RUN_ID="${EVIDENCE_RUN_ID:-}"

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
if [[ -n "${EVIDENCE_RUN_ID}" \
      && ! "${EVIDENCE_RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$ ]]; then
  echo "EVIDENCE_RUN_ID has an invalid format" >&2
  exit 2
fi
if [[ ! "${MODEL_ALIAS}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]; then
  echo "MODEL_ALIAS has an invalid evidence format" >&2
  exit 2
fi
if [[ ! "${CONTEXT_SIZE}" =~ ^[1-9][0-9]{0,8}$ \
      || ! "${PARALLEL_SLOTS}" =~ ^[1-9][0-9]{0,3}$ \
      || ! "${BATCH_SIZE}" =~ ^[1-9][0-9]{0,8}$ \
      || ! "${UBATCH_SIZE}" =~ ^[1-9][0-9]{0,8}$ ]]; then
  echo "Context, parallel, batch, and ubatch settings must be positive integers" >&2
  exit 2
fi
if [[ ! "${MODEL_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] \
    || (( MODEL_PORT > 65535 )); then
  echo "MODEL_PORT must be an integer between 1 and 65535" >&2
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
  --n-gpu-layers 999
  --ctx-size "${CONTEXT_SIZE}"
  --parallel "${PARALLEL_SLOTS}"
  --batch-size "${BATCH_SIZE}"
  --ubatch-size "${UBATCH_SIZE}"
)

help_text="$("${LLAMA_SERVER}" --help 2>&1 || true)"
if grep -q -- '--flash-attn' <<<"${help_text}"; then
  case "${FLASH_ATTN}" in
    auto|on) args+=(--flash-attn on) ;;
    off) args+=(--flash-attn off) ;;
  esac
elif [[ "${FLASH_ATTN}" == "on" ]]; then
  echo "This llama-server build does not expose --flash-attn" >&2
  exit 2
fi
if grep -q -- '--jinja' <<<"${help_text}"; then
  args+=(--jinja)
fi
if grep -q -- '--metrics' <<<"${help_text}"; then
  args+=(--metrics)
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
trap 'handle_term' TERM
trap 'forward_signal INT' INT

"${LLAMA_SERVER}" "${args[@]}" &
server_pid=$!
echo "llama_server_pid=${server_pid}"
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
