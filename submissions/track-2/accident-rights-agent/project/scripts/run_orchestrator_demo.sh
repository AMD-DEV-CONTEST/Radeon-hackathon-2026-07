#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
CASE_ID="${CASE_ID:-CASE-ORCHESTRATOR-DEMO}"
THREAD_ID="${THREAD_ID:-THREAD-ORCHESTRATOR-RECOVERY-DEMO}"

"${PYTHON_BIN}" scripts/create_orchestrator_demo.py --case-id "${CASE_ID}"
"${PYTHON_BIN}" -m app.cli orchestrate "${CASE_ID}" \
  --thread-id "${THREAD_ID}" --interrupt-after evidence_ready
"${PYTHON_BIN}" -m app.cli workflow-status "${THREAD_ID}"
"${PYTHON_BIN}" -m app.cli resume "${THREAD_ID}"
