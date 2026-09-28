#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PERSISTENT_ROOT:-}" ]]; then
  echo "ERROR: Set PERSISTENT_ROOT to the verified persistent PVC mount before running." >&2
  exit 2
fi

if [[ ! -d "$PERSISTENT_ROOT" || ! -w "$PERSISTENT_ROOT" ]]; then
  echo "ERROR: PERSISTENT_ROOT is not a writable directory: $PERSISTENT_ROOT" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_ROOT="$PERSISTENT_ROOT/brandpilot-radeon-session-1"
SOURCE_ROOT="$PERSISTENT_ROOT/source"
MODEL_CACHE="$PERSISTENT_ROOT/model-cache"
OUTPUT_ROOT="$SESSION_ROOT/outputs"
EVIDENCE_ROOT="$SESSION_ROOT/evidence"
LOG_ROOT="$SESSION_ROOT/logs"
PYTHON_BIN="${PYTHON_BIN:-python}"

mkdir -p "$SOURCE_ROOT" "$MODEL_CACHE" "$OUTPUT_ROOT" "$EVIDENCE_ROOT" "$LOG_ROOT"

for required_output in \
  "$OUTPUT_ROOT/generated-output.png" \
  "$OUTPUT_ROOT/generation-metadata.json" \
  "$OUTPUT_ROOT/generation.log"; do
  if [[ -e "$required_output" ]]; then
    echo "ERROR: Refusing to mix a new run with existing output: $required_output" >&2
    exit 2
  fi
done

export HF_HOME="$MODEL_CACHE/huggingface"
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
export TRANSFORMERS_CACHE="$HF_HOME/transformers"
export OUTPUT_DIR="$OUTPUT_ROOT"

echo "Persistent root: $PERSISTENT_ROOT"
echo "Repository: $REPO_ROOT"
echo "Model cache: $MODEL_CACHE"
echo "Outputs: $OUTPUT_ROOT"
echo "Evidence: $EVIDENCE_ROOT"
date -u +"%Y-%m-%dT%H:%M:%SZ" | tee "$EVIDENCE_ROOT/session-start-utc.txt"
cp "$REPO_ROOT/examples/browser-test-product.png" "$EVIDENCE_ROOT/rights-safe-input.png"

finish_session() {
  exit_code=$?
  date -u +"%Y-%m-%dT%H:%M:%SZ" | tee "$EVIDENCE_ROOT/session-end-utc.txt"
  printf '%s\n' "$exit_code" > "$EVIDENCE_ROOT/smoke-test-exit-code.txt"
  sync
  echo
  echo "Smoke-test command finished with exit code $exit_code. Review the evidence immediately."
  echo "IMPORTANT: this script does not stop billing or destroy the cloud instance."
  echo "Return to Radeon Cloud and use Destroy Instance before the hard deadline."
}
trap finish_session EXIT

"$PYTHON_BIN" "$REPO_ROOT/scripts/radeon_environment_check.py" \
  --output "$EVIDENCE_ROOT/environment.json" \
  2>&1 | tee "$LOG_ROOT/environment-check.log"

"$PYTHON_BIN" -m pip list --format=freeze \
  | tee "$EVIDENCE_ROOT/package-versions.txt"

"$PYTHON_BIN" "$REPO_ROOT/scripts/radeon_smoke_test.py" \
  --input "$REPO_ROOT/examples/browser-test-product.png" \
  --output-dir "$OUTPUT_ROOT" \
  --model auto \
  --revision main \
  --seed 20260725 \
  2>&1 | tee "$LOG_ROOT/smoke-test-console.log"
