#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-configs/app.yaml}"
PYTHON_BIN="${BUILDGUARD_PYTHON:-python}"

echo "== 1/7 Python and package integrity =="
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 11), f"Python 3.11 required, got {sys.version}"'
"$PYTHON_BIN" -m pip check

echo "== 2/7 Configuration =="
"$PYTHON_BIN" -m buildguard.cli validate-config --config "$CONFIG_PATH"

echo "== 3/7 Radeon, ROCm and local LLM gate =="
"$PYTHON_BIN" - "$CONFIG_PATH" <<'PY'
import sys
from pathlib import Path

from buildguard.config import load_settings
from buildguard.system.environment_probe import EnvironmentProbe

settings = load_settings(Path(sys.argv[1]))
report = EnvironmentProbe(settings).probe()

failures = []
if settings.llm.mode != "local":
    failures.append("LLM mode is not 'local'")
if not report.llm_endpoint.available:
    failures.append(f"local LLM endpoint unavailable: {report.llm_endpoint.detail}")
if not report.amd_gpu_detected:
    failures.append("no AMD GPU telemetry/device detected")
if not (
    report.commands["rocminfo"].available
    or report.commands["amd-smi"].available
    or report.commands["rocm-smi"].available
):
    failures.append("none of rocminfo, amd-smi, or rocm-smi is available")

print(report.model_dump_json(indent=2))
if failures:
    raise SystemExit("ROCm competition gate failed: " + "; ".join(failures))
PY

echo "== 4/7 Static checks and tests =="
"$PYTHON_BIN" -m ruff check src tests
"$PYTHON_BIN" -m mypy src
"$PYTHON_BIN" -m pytest -q

echo "== 5/7 Deterministic offline end-to-end workflow =="
BUILDGUARD_LLM__MODE=mock \
    "$PYTHON_BIN" -m buildguard.cli smoke-test --config "$CONFIG_PATH"

echo "== 6/7 Permission-checked tool stability =="
BUILDGUARD_LLM__MODE=mock \
    "$PYTHON_BIN" -m buildguard.cli tool-stability \
    --config "$CONFIG_PATH" \
    --iterations "${BUILDGUARD_TOOL_ITERATIONS:-50}"

echo "== 7/7 Real local LLM and ROCm benchmark =="
"$PYTHON_BIN" -m buildguard.cli benchmark-llm --config "$CONFIG_PATH"
"$PYTHON_BIN" -m buildguard.cli benchmark-suite \
    --config "$CONFIG_PATH" \
    --section rocm

echo "All automated competition gates completed."
echo "Inspect workspace/reports/evaluation and keep amd-smi visible during the real benchmark."
