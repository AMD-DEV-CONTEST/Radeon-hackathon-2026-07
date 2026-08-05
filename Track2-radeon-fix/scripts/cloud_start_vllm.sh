#!/usr/bin/env bash
set -euo pipefail

# Start the pinned local service without touching the provider's /opt/venv.
# All large paths are explicit so this script cannot accidentally use a home
# directory or a remote hosted API.
MODEL_DIR="${MODEL_DIR:-/root/models/Qwen3-14B-BF16}"
VLLM_PYTHON="${VLLM_PYTHON:-/root/radeon-code-agent-venv/bin/python}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_PROFILE="${MODEL_PROFILE:-${SCRIPT_DIR}/../configs/qwen3_14b_bf16.json}"
HOST="${VLLM_HOST:-127.0.0.1}"
PORT="${VLLM_PORT:-8000}"
LOG_FILE="${VLLM_LOG_FILE:-/root/radeon-vllm.log}"
PID_FILE="${VLLM_PID_FILE:-/root/radeon-vllm.pid}"
PREFIX_CACHING="${PREFIX_CACHING:-off}"
KV_CACHE_DTYPE="${KV_CACHE_DTYPE:-int8_per_token_head}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen3-14B-BF16}"
TOOL_CALL_PARSER="${TOOL_CALL_PARSER:-hermes}"

if [[ ! -d "${MODEL_DIR}" ]]; then
  echo "Model directory missing: ${MODEL_DIR}" >&2
  exit 2
fi
if [[ ! -x "${VLLM_PYTHON}" ]]; then
  echo "Isolated Python missing: ${VLLM_PYTHON}" >&2
  exit 2
fi
if [[ ! -f "${MODEL_PROFILE}" ]]; then
  echo "Model profile missing: ${MODEL_PROFILE}" >&2
  exit 2
fi
"${VLLM_PYTHON}" "${SCRIPT_DIR}/cloud_preflight.py" --model-dir "${MODEL_DIR}"
if [[ -f "${PID_FILE}" ]]; then
  old_pid="$(<"${PID_FILE}")"
  if [[ "${old_pid}" =~ ^[0-9]+$ ]] && kill -0 "${old_pid}" 2>/dev/null; then
    echo "vLLM already running with PID ${old_pid}" >&2
    exit 3
  fi
  rm -f "${PID_FILE}"
fi

mkdir -p "$(dirname "${LOG_FILE}")"
vllm_args=(
  "${VLLM_PYTHON}" -m vllm.entrypoints.openai.api_server
  --model "${MODEL_DIR}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --language-model-only \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser "${TOOL_CALL_PARSER}" \
  --structured-outputs-config.backend xgrammar \
  --dtype bfloat16 \
  --kv-cache-dtype "${KV_CACHE_DTYPE}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --max-num-seqs 1
)
if [[ "${PREFIX_CACHING}" == "on" ]]; then
  vllm_args+=(--enable-prefix-caching)
elif [[ "${PREFIX_CACHING}" == "off" ]]; then
  vllm_args+=(--no-enable-prefix-caching)
else
  echo "PREFIX_CACHING must be on or off" >&2
  exit 2
fi
nohup "${vllm_args[@]}" >"${LOG_FILE}" 2>&1 &
pid=$!
printf '%s\n' "${pid}" >"${PID_FILE}"
echo "Started vLLM PID ${pid}; log: ${LOG_FILE}"

for _ in $(seq 1 180); do
  if curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    echo "vLLM health check passed at http://${HOST}:${PORT}/health"
    exit 0
  fi
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "vLLM exited before health check; last log lines:" >&2
    tail -80 "${LOG_FILE}" >&2 || true
    exit 4
  fi
  sleep 2
done

echo "Timed out waiting for vLLM; last log lines:" >&2
tail -80 "${LOG_FILE}" >&2 || true
exit 5
