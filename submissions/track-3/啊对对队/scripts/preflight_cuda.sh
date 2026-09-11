#!/usr/bin/env bash
set -u

failures=0
fail() {
  echo "ERROR: $1" >&2
  failures=$((failures + 1))
}

if [[ "$(uname -s)" != "Linux" ]]; then
  fail "CUDA bootstrap expects Linux or WSL2"
fi
for command_name in python3 git nvidia-smi; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    fail "missing required command: ${command_name}"
  fi
done

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || fail "nvidia-smi failed"
fi

if command -v python3 >/dev/null 2>&1; then
  if ! python3 - <<'PY'
import json
import sys

try:
    import torch
except ImportError as exc:
    raise SystemExit(f"CUDA PyTorch is missing: {exc}")

if torch.version.cuda is None or torch.version.hip is not None:
    raise SystemExit("this is not an NVIDIA PyTorch CUDA build")
if not torch.cuda.is_available():
    raise SystemExit("PyTorch CUDA cannot access the NVIDIA GPU")

print(json.dumps({
    "python": sys.version.split()[0],
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "device": torch.cuda.get_device_name(0),
    "memory_gib": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2),
}, indent=2))
PY
  then
    fail "Python/CUDA preflight failed"
  fi
fi

if (( failures > 0 )); then
  echo "CUDA preflight failed with ${failures} blocking issue(s)." >&2
  exit 1
fi
echo "CUDA preflight passed."
