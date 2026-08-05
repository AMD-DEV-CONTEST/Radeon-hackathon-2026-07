#!/usr/bin/env bash
set -euo pipefail

export TRACK2_BASE_URL="${TRACK2_BASE_URL:-https://developer.amd.com.cn/radeon/api/v1}"
export TRACK2_MODEL="${TRACK2_MODEL:-Qwen3.6-35B-A3B}"
TRACK2_KEYCHAIN_SERVICE="${TRACK2_KEYCHAIN_SERVICE:-hermes-track2-amd}"

if [[ -z "${TRACK2_API_KEY:-}" && "$(uname -s)" == "Darwin" ]] && command -v security >/dev/null 2>&1; then
  TRACK2_API_KEY="$(security find-generic-password \
    -a "${USER}" \
    -s "${TRACK2_KEYCHAIN_SERVICE}" \
    -w 2>/dev/null || true)"
  export TRACK2_API_KEY
fi

: "${TRACK2_API_KEY:?Set TRACK2_API_KEY or run scripts/store_track2_keychain.sh first}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -f "${ROOT_DIR}/tasks/smoke-manifest.jsonl" ]]; then
  echo "Missing tasks/smoke-manifest.jsonl; prepare the fixed task workspaces first." >&2
  exit 1
fi

mkdir -p "${ROOT_DIR}/runs/api-smoke"
exec "${PYTHON}" "${ROOT_DIR}/track2_eval.py" \
  --prompts_file "${ROOT_DIR}/tasks/smoke-manifest.jsonl" \
  --output_dir "${ROOT_DIR}/runs/api-smoke" \
  --env local \
  --max_iterations "${TRACK2_MAX_ITERATIONS:-15}" \
  --timeout "${TRACK2_COMMAND_TIMEOUT:-120}" \
  --api_timeout "${TRACK2_API_TIMEOUT:-120}" \
  --variant C0-J0-V0 \
  --variant C1-J0-V0 \
  --variant C2-J0-V0 \
  --variant C3-J0-V0 \
  --variant C0-J1-V0 \
  --variant C0-J2-V0 \
  --variant C0-J0-V1 \
  --variant C0-J0-V2 \
  --variant C0-J2-V2 \
  --variant C0-J3-V1 \
  --variant C0-J3-V2
