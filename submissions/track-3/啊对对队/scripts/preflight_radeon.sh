#!/usr/bin/env bash
set -u

failures=0

fail() {
  echo "ERROR: $1" >&2
  failures=$((failures + 1))
}

warn() {
  echo "WARN: $1" >&2
}

if [[ "$(uname -s)" != "Linux" ]]; then
  fail "Radeon bootstrap expects Linux"
fi

for command_name in python3 git; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    fail "missing required command: ${command_name}"
  fi
done

if [[ ! -e /dev/kfd ]]; then
  fail "/dev/kfd is missing; ROCm compute is not exposed to this container"
fi
if [[ ! -d /dev/dri ]]; then
  fail "/dev/dri is missing; Radeon render devices are not exposed"
fi

if command -v rocm-smi >/dev/null 2>&1; then
  rocm-smi --showproductname --showmeminfo vram || warn "rocm-smi returned an error"
else
  warn "rocm-smi is unavailable; PyTorch HIP will remain the authoritative check"
fi

if command -v python3 >/dev/null 2>&1; then
  if ! python3 - <<'PY'
import json
import sys

try:
    import torch
except ImportError as exc:
    raise SystemExit(f"ROCm PyTorch is missing: {exc}")

hip = getattr(torch.version, "hip", None)
if hip is None:
    raise SystemExit("torch.version.hip is empty; this is not a ROCm PyTorch build")
if not torch.cuda.is_available():
    raise SystemExit("PyTorch HIP cannot access the Radeon GPU")
if torch.cuda.device_count() != 1:
    raise SystemExit(f"expected one visible GPU, found {torch.cuda.device_count()}")
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ is required, found {sys.version.split()[0]}")

print(json.dumps({
    "python": sys.version.split()[0],
    "torch": torch.__version__,
    "rocm": hip,
    "device": torch.cuda.get_device_name(0),
    "device_count": torch.cuda.device_count(),
}, indent=2))
PY
  then
    fail "Python/ROCm preflight failed"
  fi

  if ! python3 -c "import venv" >/dev/null 2>&1; then
    fail "Python venv module is unavailable"
  fi
fi

available_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
if [[ -n "${available_kb}" ]] && (( available_kb < 10485760 )); then
  warn "less than 10 GiB is available in the current filesystem"
fi

if (( failures > 0 )); then
  echo "Preflight failed with ${failures} blocking issue(s)." >&2
  exit 1
fi

echo "Radeon Cloud preflight passed."
