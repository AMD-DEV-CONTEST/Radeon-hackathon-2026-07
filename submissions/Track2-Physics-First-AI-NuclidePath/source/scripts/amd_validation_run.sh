#!/usr/bin/env bash
# NuclidePath — reproducible AMD/ROCm validation for the current checkout.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_SOURCE_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
CALLER_DIR=$(pwd -P)
SOURCE_DIR="${1:-$DEFAULT_SOURCE_DIR}"
OUTDIR="${2:-$SOURCE_DIR/artifacts/amd-validation-current}"
PYTHON="${PYTHON:-python3}"
LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:8000/v1}"
LLM_MODEL="${LLM_MODEL:-qwen35-9b-q8}"
SAMPLES="${SAMPLES:-128}"
SEED="${SEED:-42}"
SCENARIO="${SCENARIO:-scenarios/cs137_emergency_full.json}"

if [[ "$SOURCE_DIR" != /* ]]; then
  SOURCE_DIR="$CALLER_DIR/$SOURCE_DIR"
fi
if [[ ! -f "$SOURCE_DIR/pyproject.toml" ]]; then
  echo "ERROR: source checkout not found at $SOURCE_DIR" >&2
  exit 2
fi
SOURCE_DIR=$(cd -- "$SOURCE_DIR" && pwd -P)
if [[ "$OUTDIR" != /* ]]; then
  OUTDIR="$CALLER_DIR/$OUTDIR"
fi
if [[ -z "$OUTDIR" || "$OUTDIR" == "/" || "$OUTDIR" == "$SOURCE_DIR" ]]; then
  echo "ERROR: unsafe output directory: $OUTDIR" >&2
  exit 2
fi
mkdir -p "$OUTDIR"
OUTDIR=$(cd -- "$OUTDIR" && pwd -P)
cd "$SOURCE_DIR"

echo "=== NuclidePath AMD validation — $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" \
  | tee "$OUTDIR/validation.log"

# Install the current checkout without replacing the caller's ROCm PyTorch build.
"$PYTHON" -m pip install -e . 2>&1 | tee "$OUTDIR/install.log"

# Preserve pytest output and its real exit status under pipefail.
set +e
"$PYTHON" -m pytest tests/ -q -rs 2>&1 | tee "$OUTDIR/test-results.txt"
test_exit=${PIPESTATUS[0]}
set -e
if (( test_exit != 0 )); then
  echo "ERROR: regression gate failed ($test_exit)" | tee -a "$OUTDIR/validation.log"
  exit "$test_exit"
fi

curl -fsS "$LLM_BASE_URL/models" > "$OUTDIR/models.json" || {
  echo "ERROR: local LLM endpoint unavailable at $LLM_BASE_URL" >&2
  exit 3
}

rm -rf "$OUTDIR/offline" "$OUTDIR/llm-planned"
start_ns=$(date +%s%N)
"$PYTHON" -m nuclear_agent.demo \
  --scenario "$SCENARIO" --output "$OUTDIR/offline" \
  --planner deterministic --samples "$SAMPLES" --seed "$SEED" \
  --session-id amd-validation-offline 2>&1 | tee "$OUTDIR/offline-run.log"
end_ns=$(date +%s%N)
"$PYTHON" -c "print(($end_ns-$start_ns)/1e9)" > "$OUTDIR/offline-elapsed-s.txt"

start_ns=$(date +%s%N)
"$PYTHON" -m nuclear_agent.demo \
  --scenario "$SCENARIO" --output "$OUTDIR/llm-planned" \
  --planner llm --llm-base-url "$LLM_BASE_URL" --llm-model "$LLM_MODEL" \
  --samples "$SAMPLES" --seed "$SEED" --session-id amd-validation-llm \
  2>&1 | tee "$OUTDIR/llm-run.log"
end_ns=$(date +%s%N)
"$PYTHON" -c "print(($end_ns-$start_ns)/1e9)" > "$OUTDIR/llm-elapsed-s.txt"

"$PYTHON" - "$OUTDIR" <<'PY' | tee "$OUTDIR/parity.txt"
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
offline = json.loads((root / "offline/report.json").read_text(encoding="utf-8"))
planned = json.loads((root / "llm-planned/report.json").read_text(encoding="utf-8"))
keys = ("scenario", "comparison", "runs", "assumptions", "warnings", "sensitivity", "uncertainty")
comparisons = {key: offline[key] == planned[key] for key in keys}
print(json.dumps({"comparisons": comparisons, "physical_parity": all(comparisons.values())}, indent=2))
if not all(comparisons.values()):
    raise SystemExit("ERROR: deterministic and LLM-planned physics differ")
PY

"$PYTHON" scripts/amd_transport_benchmark.py \
  --output "$OUTDIR/transport-benchmark.json" \
  --sizes 1 128 4096 65536 --repeats 5

"$PYTHON" scripts/benchmark_primary_gcs.py \
  --output "$OUTDIR/primary-gcs-exact-batch-fp64.json" \
  --size 100000 --repeats 5 --device cuda --dtype float64

"$PYTHON" - "$OUTDIR" <<'PY'
import datetime
import json
import platform
import subprocess
import sys
from pathlib import Path

import torch

props = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None
total_memory = None if props is None else getattr(props, "total_memory", getattr(props, "total_mem", None))
metadata = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "release": "transport-prototype-0.3",
    "platform": platform.platform(),
    "python": platform.python_version(),
    "torch": torch.__version__,
    "hip": torch.version.hip,
    "hip_available": torch.cuda.is_available(),
    "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "gpu_vram_gb_decimal": total_memory / 1e9 if total_memory else None,
    "validation_command": "scripts/amd_validation_run.sh [SOURCE_DIR] [OUTDIR]",
    "transport_benchmark": {
        "sizes": [1, 128, 4096, 65536],
        "repeats": 5,
        "fp64_max_relative_error_tolerance": 1.0e-12,
        "fp32_max_relative_error_reporting_threshold": 1.0e-4,
    },
}
try:
    metadata["source_revision"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=Path.cwd(), check=True,
        capture_output=True, text=True,
    ).stdout.strip()
except (OSError, subprocess.CalledProcessError):
    metadata["source_revision"] = "unavailable-non-git-checkout"
Path(sys.argv[1], "benchmark-metadata.json").write_text(
    json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
)
PY

echo "=== Validation complete: $OUTDIR ===" | tee -a "$OUTDIR/validation.log"
