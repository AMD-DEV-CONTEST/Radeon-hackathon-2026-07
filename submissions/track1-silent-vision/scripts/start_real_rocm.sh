#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PERSISTENCE_ROOT="${PERSISTENCE_ROOT:-/workspace/persistent/silent-vision}"
export TORCH_HOME="${TORCH_HOME:-$PERSISTENCE_ROOT/cache/torch}"
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-*}"
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

"$PYTHON_BIN" - <<'PY'
import os
import sys
from pathlib import Path
import torch

print("python:", sys.executable)
print("torch:", torch.__version__)
print("torch hip:", torch.version.hip)
print("cuda available:", torch.cuda.is_available())
print("device count:", torch.cuda.device_count())
if torch.version.hip is None:
    raise SystemExit("ROCm PyTorch is not available; refusing to start real mode")
if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
    raise SystemExit("ROCm device cuda:0 is not available; refusing to start real mode")
device = torch.device("cuda:0")
probe = torch.empty(1, device=device)
print("selected device:", device)
print("device name:", torch.cuda.get_device_name(0))
del probe

root = Path(os.environ["PERSISTENCE_ROOT"])
backend = os.environ["COMMAND_BACKEND"]
print("command backend:", backend)
print("persistence root:", root)
if backend == "torch":
    print("phrase checkpoint:", os.environ["COMMAND_CLASSIFIER_CHECKPOINT"])
else:
    profile_root = root / "profiles"
    profile_root.mkdir(parents=True, exist_ok=True)
    print("recording profiles:", profile_root)
PY

"$PYTHON_BIN" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level "${LOG_LEVEL:-info}"
