#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-/workspace/rdna/bin/python}"
PYTHONPATH=src
PROTOCOL="configs/controller_probe_confirmation_v5.toml"
OUTPUT_ROOT="outputs/controller-probe-v5"
MANIFEST="$OUTPUT_ROOT/candidates/confirmation/manifest.json"

echo "[1/3] audit frozen V5 protocol"
PYTHONPATH="$PYTHONPATH" "$PYTHON_BIN" \
  scripts/audit_controller_probe_confirmation_protocol.py \
  --protocol "$PROTOCOL" \
  --output "$OUTPUT_ROOT/protocol-audit.json"

echo "[2/3] collect independent Radeon rollouts (resume-safe)"
PYTHONPATH="$PYTHONPATH" "$PYTHON_BIN" \
  scripts/run_controller_probe_confirmation_collection.py \
  --protocol "$PROTOCOL" \
  --config configs/catalog_v2.toml \
  --backend rocm \
  --max-candidates 6 \
  --repeats 1 \
  --resume \
  --output-dir "$OUTPUT_ROOT/candidates"

echo "[3/3] evaluate exactly once after all 80 sources are complete"
PYTHONPATH="$PYTHONPATH" "$PYTHON_BIN" \
  scripts/evaluate_controller_probe_confirmation.py \
  --protocol "$PROTOCOL" \
  --manifest "/workspace/parcel-sorter-opt-v1/$MANIFEST" \
  --dataset-output "$OUTPUT_ROOT/confirmation-dataset.json" \
  --output "$OUTPUT_ROOT/confirmation-result.json"
