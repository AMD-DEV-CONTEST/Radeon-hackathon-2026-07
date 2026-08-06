#!/usr/bin/env bash
# One-command reproducible setup for the radeon-fix product (Track 2).
#
# Creates the main project venv, installs the project, clones the pinned Aider
# commit, creates benchmarks/aider/.venv-track2 with Aider's Repo Map
# dependencies, runs a Repo Map smoke test, and checks the local vLLM endpoint
# and xgrammar structured-output capability.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIDER_DIR="${ROOT_DIR}/benchmarks/aider"
AIDER_REV="5dc9490bb35f9729ef2c95d00a19ccd30c26339c"
VENV_DIR="${ROOT_DIR}/.venv"
AIDER_VENV="${AIDER_DIR}/.venv-track2"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BASE_URL="${TRACK2_BASE_URL:-http://127.0.0.1:8000/v1}"
MODEL="${TRACK2_MODEL:-Qwen3-14B-BF16}"

echo "[1/5] Main project virtual environment"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -e "${ROOT_DIR}[dev]"

echo "[2/5] Aider pinned checkout (${AIDER_REV})"
mkdir -p "${ROOT_DIR}/benchmarks"
if [[ ! -d "${AIDER_DIR}/.git" ]]; then
  git clone --quiet --filter=blob:none https://github.com/Aider-AI/aider.git "${AIDER_DIR}"
fi
git -C "${AIDER_DIR}" fetch --quiet --depth 1 origin "${AIDER_REV}"
git -C "${AIDER_DIR}" checkout --quiet --detach "${AIDER_REV}"

echo "[3/5] Aider Repo Map venv (benchmarks/aider/.venv-track2)"
if [[ ! -x "${AIDER_VENV}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${AIDER_VENV}"
fi
"${AIDER_VENV}/bin/pip" install --quiet --upgrade pip
"${AIDER_VENV}/bin/pip" install --quiet -e "${AIDER_DIR}"

echo "[4/5] Repo Map smoke test"
SMOKE_OUT="$("${AIDER_VENV}/bin/python" "${ROOT_DIR}/track2_context_extract.py" \
  --provider aider \
  --root "${ROOT_DIR}/examples/demo_project" \
  --aider-root "${AIDER_DIR}" \
  --model "openai/${MODEL}" \
  --map-tokens 2048 \
  --issue "setup smoke test")"
if [[ -z "${SMOKE_OUT}" ]]; then
  echo "ERROR: Repo Map smoke test produced no context. Check ${AIDER_VENV}." >&2
  exit 1
fi
echo "Repo Map smoke test: OK (${#SMOKE_OUT} chars)"

echo "[5/5] Local vLLM endpoint and J3/xgrammar checks"
if curl -sS --max-time 5 "${BASE_URL}/models" 2>/dev/null | grep -q '"id"'; then
  echo "vLLM endpoint ${BASE_URL}: OK"
else
  echo "WARNING: vLLM endpoint ${BASE_URL} is not reachable. Start it with" >&2
  echo "  ${ROOT_DIR}/scripts/cloud_start_vllm.sh  (or your local launcher)" >&2
fi
"${VENV_DIR}/bin/python" - "${BASE_URL}" "${MODEL}" <<'PY'
import json
import os
import sys

base_url = sys.argv[1]
model = sys.argv[2]
api_key = os.environ.get("TRACK2_API_KEY", "local-vllm")
try:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=20)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": 'Return the JSON object {"ok": true}.'}],
        response_format={"type": "json_object"},
        max_tokens=64,
    )
    json.loads(response.choices[0].message.content)
    print("J3/xgrammar structured output: OK")
except Exception as exc:  # noqa: BLE001 - setup diagnostics only
    print("WARNING: J3/xgrammar structured output unavailable: " + str(exc)[:300])
    print("Start vLLM with --structured-outputs-config.backend xgrammar.")
PY

echo "READY"
