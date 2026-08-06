#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PERSISTENCE_ROOT="${PERSISTENCE_ROOT:-${SV_ROOT:-/workspace/persistent/silent-vision}}"
export SV_ROOT="${SV_ROOT:-$PERSISTENCE_ROOT}"
export TORCH_HOME="${TORCH_HOME:-$PERSISTENCE_ROOT/cache/torch}"
export PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
export COMMAND_BACKEND="${COMMAND_BACKEND:-torch}"
export COMMAND_CLASSIFIER_CHECKPOINT="${COMMAND_CLASSIFIER_CHECKPOINT:-$PERSISTENCE_ROOT/models/fixed-phrase.pt}"

if [[ "$COMMAND_BACKEND" != "torch" && "$COMMAND_BACKEND" != "prototype" ]]; then
  echo "COMMAND_BACKEND must be torch or prototype recording mode" >&2
  exit 1
fi
if [[ "$COMMAND_BACKEND" == "torch" && ! -s "$COMMAND_CLASSIFIER_CHECKPOINT" ]]; then
  echo "Torch phrase checkpoint not found: $COMMAND_CLASSIFIER_CHECKPOINT" >&2
  exit 1
fi

mkdir -p \
  "$SV_ROOT/logs" \
  "$SV_ROOT/logs/command-runs" \
  "$SV_ROOT/profiles/global" \
  "$SV_ROOT/models" \
  "$TORCH_HOME"

check_no_removed_dependencies() {
  if grep -E '^(transformers|huggingface-hub|accelerate|safetensors|librosa|soundfile|minicpmo-utils)([<=> ]|$)' requirements.txt; then
    echo "removed open-vocabulary model dependency found in requirements.txt" >&2
    exit 1
  fi
}

check_rocm_python() {
  "$PYTHON_BIN" - <<'PY'
import sys
import torch

print("python:", sys.executable)
print("torch:", torch.__version__)
print("torch hip:", torch.version.hip)
print("cuda available:", torch.cuda.is_available())
print("device count:", torch.cuda.device_count())
if torch.version.hip is None:
    raise SystemExit("ROCm PyTorch is not available in this Python environment")
if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
    raise SystemExit("ROCm device cuda:0 is not available in this Python environment")
device = torch.device("cuda:0")
probe = torch.empty(1, device=device)
print("selected device:", device)
print("device name:", torch.cuda.get_device_name(0))
del probe
PY
}

check_app_dependencies() {
  "$PYTHON_BIN" - <<'PY'
from importlib import metadata

for package in ["fastapi", "uvicorn", "pydantic", "numpy", "cv2", "mediapipe", "av", "PIL"]:
    try:
        module_name = "opencv-python-headless" if package == "cv2" else "pillow" if package == "PIL" else package
        print(f"{package}:", metadata.version(module_name))
    except Exception as exc:
        raise SystemExit(f"missing required runtime dependency {package}: {exc}") from exc

import mediapipe as mp
solutions = getattr(mp, "solutions", None)
if solutions is not None:
    face_mesh = solutions.face_mesh
else:
    from mediapipe.python.solutions import face_mesh
print("FaceMesh:", face_mesh.FaceMesh)
PY
}

check_no_removed_dependencies
check_rocm_python
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install --upgrade -r requirements.txt
check_rocm_python
check_app_dependencies

echo "setup complete: COMMAND_BACKEND=$COMMAND_BACKEND"
