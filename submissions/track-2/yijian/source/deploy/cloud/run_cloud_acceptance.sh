#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
VENV="$PERSIST_ROOT/venv"

cd "$PROJECT_ROOT"
echo "[1/5] AMD and service smoke test"
bash deploy/cloud/smoke_test.sh

echo "[2/5] Python regression"
"$VENV/bin/python" -m pytest backend/tests -q

echo "[3/5] Go rules cross-check"
node backend/tests/crosscheck.mjs backend/tests/recommendation-smoke.sgf

echo "[4/5] Browser acceptance"
PLAYWRIGHT_BROWSERS_PATH="$PERSIST_ROOT/playwright" \
  "$VENV/bin/python" backend/tests/ui_check.py "$PERSIST_ROOT/benchmarks/ui"

echo "[5/5] 4B / 30B mentor benchmarks"
YIJIAN_CLOUD_LLM_URL="http://127.0.0.1:8081/v1" \
YIJIAN_CLOUD_LLM_MODEL="Qwen3-4B-Q4_K_M" \
  "$VENV/bin/python" deploy/cloud/benchmark_mentor.py
"$VENV/bin/python" deploy/cloud/benchmark_mentor.py
echo "W7900 acceptance passed."
