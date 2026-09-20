#!/usr/bin/env bash
# Reproducible Track 2 submission verification for the domestic-market Agent.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${VENV_PYTHON:-python3}"
VLLM_URL="${VLLM_URL:-http://127.0.0.1:8000/v1}"
API_URL="${API_URL:-http://127.0.0.1:8080}"
MODEL_NAME="${MODEL_NAME:-models/qwen-trader-merged}"
OUTPUT="${EVAL_OUTPUT:-${PROJECT_ROOT}/artifacts/cn_market_eval_reproduced.json}"

cd "${PROJECT_ROOT}"

echo "[1/5] Repository policy check"
if rg -n -i 'btc|eth/usdt|binance|crypto trading agent' README.md docs/technical_report.md docs/track2_demo_script_cn.md; then
  echo "ERROR: forbidden legacy-market content found in submission-facing docs"
  exit 1
fi

echo "[2/5] Local API health"
curl -fsS "${API_URL}/health" >/dev/null

echo "[3/5] AMD-local vLLM model"
MODELS_JSON="$(curl -fsS "${VLLM_URL}/models")"
printf '%s' "${MODELS_JSON}" | "${PYTHON}" -c \
  'import json,sys; expected=sys.argv[1]; d=json.load(sys.stdin); ids=[x["id"] for x in d.get("data",[])]; assert expected in ids, (expected,ids); print("model:",expected)' \
  "${MODEL_NAME}"

echo "[4/5] Stable core tests"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "${PYTHON}" -m pytest -q \
  tests/test_cn_market.py \
  tests/test_dsl_validator.py

echo "[5/5] 24-case CN-market evaluation"
"${PYTHON}" scripts/eval_cn_market_v2.py \
  --vllm-url "${VLLM_URL}" \
  --model "${MODEL_NAME}" \
  --output "${OUTPUT}" \
  --max-retries 2

"${PYTHON}" - "${OUTPUT}" <<'PY'
import json, sys
path = sys.argv[1]
summary = json.load(open(path, encoding="utf-8"))["summary"]
assert summary["passed"] == summary["total"], summary
print("submission verification: PASS", summary)
PY
