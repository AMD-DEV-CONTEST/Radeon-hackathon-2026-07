#!/usr/bin/env bash
# run_smoke_chain.sh — Chain 4 sequential smoke runs after the current cloaked run finishes.
#
# Runs in order:
#   1. Clean uncloaked      (Cloak OFF, RAG ON)
#   2. Clean cloaked        (Cloak ON,  RAG ON)
#   3. No-RAG uncloaked     (Cloak OFF, RAG OFF)
#   4. No-RAG cloaked       (Cloak ON,  RAG OFF)
#
# This gives a 2x2 ablation table:
#
#           | Cloak OFF      | Cloak ON
#   --------+----------------+------------------
#   RAG ON  | run 1          | run 2
#   RAG OFF | run 3          | run 4
#
# Usage: bash scripts/run_smoke_chain.sh

set -euo pipefail
cd "$(dirname "$0")/.."

BASE_ARGS="--config b --split lite --instances 9 --parallel 3"

echo "============================================================"
echo "CHAIN: 4 smoke runs queued"
echo "============================================================"

echo "[CHAIN 1/4] Clean uncloaked (Cloak OFF, RAG ON)"
python3 scripts/determinex_swebench_run.py $BASE_ARGS \
  --name "smoke-clean-uncloaked" \
  --note "clean pipeline: Cloak OFF, RAG ON (v4 routing + attempt_idx + REPLACE lineno fix)"

echo "[CHAIN 2/4] Clean cloaked (Cloak ON, RAG ON)"
python3 scripts/determinex_swebench_run.py $BASE_ARGS --cloak \
  --name "smoke-clean-cloaked" \
  --note "clean pipeline: Cloak ON, RAG ON"

echo "[CHAIN 3/4] No-RAG uncloaked (Cloak OFF, RAG OFF)"
DETERMINEX_NO_ROSETTA=1 python3 scripts/determinex_swebench_run.py $BASE_ARGS \
  --name "smoke-norag-uncloaked" \
  --note "RAG ablation: Cloak OFF, DETERMINEX_NO_ROSETTA=1 (no flywheel corpus retrieval)"

echo "[CHAIN 4/4] No-RAG cloaked (Cloak ON, RAG OFF)"
DETERMINEX_NO_ROSETTA=1 python3 scripts/determinex_swebench_run.py $BASE_ARGS --cloak \
  --name "smoke-norag-cloaked" \
  --note "RAG ablation: Cloak ON, DETERMINEX_NO_ROSETTA=1 (no flywheel corpus retrieval)"

echo "============================================================"
echo "CHAIN COMPLETE — all 4 smoke runs finished"
echo "============================================================"
