#!/usr/bin/env bash
set -uo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
VLLM_PYTHON="${VLLM_PYTHON:-$ROOT/venvs/vllm/bin/python}"
failures=0

section() {
  printf '\n[%s]\n' "$1"
}

run_check() {
  local label="$1"
  shift
  printf '%-28s' "$label"
  if "$@" >/tmp/amd-track2-check.out 2>&1; then
    echo "PASS"
    sed -n '1,8p' /tmp/amd-track2-check.out
  else
    echo "FAIL"
    sed -n '1,12p' /tmp/amd-track2-check.out
    failures=$((failures + 1))
  fi
}

section "Persistence"
if [[ "$(pwd)" == /workspace* ]]; then
  echo "PASS: current directory is persistent: $(pwd)"
else
  echo "WARN: current directory is not under /workspace: $(pwd)"
fi

section "GPU and ROCm"
run_check "amd-smi" amd-smi static
run_check "rocminfo gfx target" bash -lc "rocminfo | grep -m 3 -E 'Name:.*gfx|Marketing Name'"
run_check "/dev/kfd" test -e /dev/kfd
run_check "/dev/dri" test -d /dev/dri

section "Python stack"
run_check "python" python3 --version
if [[ ! -x "$VLLM_PYTHON" ]]; then
  VLLM_PYTHON="$(command -v python3)"
fi
echo "Inference Python: $VLLM_PYTHON"
run_check "PyTorch ROCm" "$VLLM_PYTHON" -c \
  "import torch; print('torch', torch.__version__); print('hip', torch.version.hip); print('gpu', torch.cuda.get_device_name(0)); print('available', torch.cuda.is_available())"
run_check "GPU tensor smoke" "$VLLM_PYTHON" -c \
  "import torch; x=torch.arange(8, device='cuda', dtype=torch.float32); print((x*x).cpu().tolist())"
run_check "vLLM ROCm wheel" "$VLLM_PYTHON" -c \
  "import importlib.metadata, vllm; from vllm.platforms import current_platform; v=importlib.metadata.version('vllm'); print(v); print(type(current_platform).__name__); assert '.rocm' in v; assert type(current_platform).__name__ == 'RocmPlatform'"
run_check "vLLM CLI" "${VLLM_PYTHON%/python}/vllm" --help

section "Container tools"
if command -v podman >/dev/null 2>&1; then
  run_check "podman" podman --version
else
  echo "INFO: podman is not installed in this image. It is optional for the Python-first route."
fi

section "Disk"
df -h /workspace 2>/dev/null || df -h .

rm -f /tmp/amd-track2-check.out

if (( failures > 0 )); then
  echo
  echo "Completed with $failures failed check(s). See docs/DEVELOPMENT_ENVIRONMENT.md."
  exit 1
fi

echo
echo "ROCm environment checks passed."
