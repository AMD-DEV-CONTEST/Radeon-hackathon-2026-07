#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export COMMAND_BACKEND="${COMMAND_BACKEND:-torch}"
export PERSISTENCE_ROOT="${PERSISTENCE_ROOT:-/workspace/persistent/silent-vision}"
export PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
export COMMAND_CLASSIFIER_CHECKPOINT="${COMMAND_CLASSIFIER_CHECKPOINT:-$PERSISTENCE_ROOT/models/fixed-phrase.pt}"

if [[ "$COMMAND_BACKEND" != "torch" ]]; then
  echo "ROCm classifier smoke requires COMMAND_BACKEND=torch" >&2
  exit 1
fi
if [[ ! -s "$COMMAND_CLASSIFIER_CHECKPOINT" ]]; then
  echo "Torch phrase checkpoint not found: $COMMAND_CLASSIFIER_CHECKPOINT" >&2
  exit 1
fi
if [[ -z "${COMMAND_SMOKE_SAMPLE:-}" || ! -s "$COMMAND_SMOKE_SAMPLE" ]]; then
  echo "Mouth ROI smoke sample not found: ${COMMAND_SMOKE_SAMPLE:-<unset>}" >&2
  exit 1
fi
if [[ "${COMMAND_SMOKE_LANGUAGE:-}" != "zh" && "${COMMAND_SMOKE_LANGUAGE:-}" != "en" ]]; then
  echo "COMMAND_SMOKE_LANGUAGE must be zh or en" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import torch

print("torch:", torch.__version__)
print("torch hip:", torch.version.hip)
print("cuda available:", torch.cuda.is_available())
print("device count:", torch.cuda.device_count())
if torch.version.hip is None:
    raise SystemExit("ROCm PyTorch is not available")
if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
    raise SystemExit("ROCm device cuda:0 is not available")
device = torch.device("cuda:0")
probe = torch.empty(1, device=device)
print("selected device:", device)
print("device name:", torch.cuda.get_device_name(0))
del probe
PY

"$PYTHON_BIN" -m pytest \
  tests/test_phrase_model.py \
  tests/test_phrase_checkpoint.py \
  tests/test_phrase_runtime.py \
  -q

prediction_output="$(mktemp)"
cleanup() {
  rm -f -- "$prediction_output"
}
trap cleanup EXIT

"$PYTHON_BIN" scripts/infer_command_clip.py \
  --checkpoint "$COMMAND_CLASSIFIER_CHECKPOINT" \
  --mouth-roi "$COMMAND_SMOKE_SAMPLE" \
  --language "$COMMAND_SMOKE_LANGUAGE" \
  | tee "$prediction_output"

SMOKE_PREDICTION_OUTPUT="$prediction_output" "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["SMOKE_PREDICTION_OUTPUT"])
try:
    result = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"classifier smoke did not return valid JSON: {exc}") from exc

if result.get("backend") != "torch":
    raise SystemExit(f"classifier smoke backend must be torch, got {result.get('backend')!r}")
if result.get("device") != "cuda:0":
    raise SystemExit(f"classifier smoke device must be cuda:0, got {result.get('device')!r}")
threshold_source = result.get("thresholdSource")
if not isinstance(threshold_source, str) or not threshold_source:
    raise SystemExit("classifier smoke must report a threshold source")
print("classifier prediction verified on torch cuda:0; threshold source:", threshold_source)
PY
