#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
VENV="${VLLM_VENV:-$ROOT/venvs/vllm}"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$(dirname "$SCRIPT_DIR")}"
PIN_FILE="$REPO/config/runtime/vllm-rocm721-known-good.env"

if [[ "$ROOT" != /workspace/* ]]; then
  echo "ERROR: keep the environment under /workspace so it survives pod rebuilds."
  exit 1
fi

if [[ ! -f "$PIN_FILE" ]]; then
  echo "ERROR: frozen vLLM pin file not found: $PIN_FILE"
  exit 1
fi

if [[ -n "${VLLM_PIN_FILE:-}" ]]; then
  echo "ERROR: overriding the reviewed vLLM pin file is not allowed."
  exit 1
fi

# shellcheck disable=SC1090
source "$PIN_FILE"
: "${VLLM_EXPECTED_VERSION:?missing from $PIN_FILE}"
: "${VLLM_WHEEL_COMMIT:?missing from $PIN_FILE}"
: "${VLLM_ROCM_VARIANT:?missing from $PIN_FILE}"
: "${VLLM_WHEEL_URL:?missing from $PIN_FILE}"
: "${VLLM_WHEEL_SHA256:?missing from $PIN_FILE}"
: "${VLLM_DEPENDENCY_INDEX:?missing from $PIN_FILE}"

if [[ -x "$VENV/bin/uv" ]]; then
  UV="$VENV/bin/uv"
elif command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
  [[ -x "$VENV/bin/python" ]] || "$UV" venv "$VENV" --python 3.12 --seed
else
  [[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip uv
  UV="$VENV/bin/uv"
fi

"$VENV/bin/python" -c \
  'import sys; assert sys.version_info[:2] == (3, 12), sys.version'

WHEEL_CACHE="${VLLM_WHEEL_CACHE:-$ROOT/cache/wheels}"
wheel_filename="$(
  python3 -c 'import os, sys, urllib.parse; print(urllib.parse.unquote(os.path.basename(sys.argv[1])))' \
    "$VLLM_WHEEL_URL"
)"
wheel_path="$WHEEL_CACHE/$wheel_filename"

mkdir -p "$WHEEL_CACHE" "$LOG_DIR"
if [[ -f "$wheel_path" ]] && ! echo "$VLLM_WHEEL_SHA256  $wheel_path" | sha256sum --check --status; then
  echo "WARN: removing cached vLLM wheel with the wrong SHA-256: $wheel_path"
  rm -f "$wheel_path"
fi
if [[ ! -f "$wheel_path" ]]; then
  echo "Downloading frozen vLLM wheel from commit $VLLM_WHEEL_COMMIT"
  curl -fL --retry 3 --retry-delay 2 --output "$wheel_path.part" "$VLLM_WHEEL_URL"
  echo "$VLLM_WHEEL_SHA256  $wheel_path.part" | sha256sum --check --status || {
    rm -f "$wheel_path.part"
    echo "ERROR: downloaded vLLM wheel failed SHA-256 verification."
    exit 1
  }
  mv "$wheel_path.part" "$wheel_path"
fi
echo "$VLLM_WHEEL_SHA256  $wheel_path" | sha256sum --check --status || {
  echo "ERROR: cached vLLM wheel failed SHA-256 verification."
  exit 1
}

installed_version="$(
  "$VENV/bin/python" -c 'from importlib.metadata import version; print(version("vllm"))' \
    2>/dev/null || true
)"

if [[ "$installed_version" == "$VLLM_EXPECTED_VERSION" ]]; then
  echo "The explicit vLLM ROCm wheel is already installed: $installed_version"
else
  echo "Installing frozen vLLM ROCm wheel: $wheel_path"
  UV_LINK_MODE=copy "$UV" pip install --python "$VENV/bin/python" --pre --upgrade \
    "$wheel_path" \
    --extra-index-url "$VLLM_DEPENDENCY_INDEX" \
    --index-strategy unsafe-best-match
fi

# A previous unpinned install may have selected PyPI's CUDA vLLM and left these
# CUDA-only optional packages behind. They are not dependencies of the ROCm
# wheel and can make ROCm warmup import libcudart by mistake.
"$VENV/bin/python" -m pip uninstall -y \
  flashinfer-python flashinfer-cubin PyNvVideoCodec >/dev/null 2>&1 || true

VLLM_EXPECTED_VERSION="$VLLM_EXPECTED_VERSION" "$VENV/bin/python" - <<'PY'
import os
from importlib.metadata import version

import torch
import vllm
from vllm.platforms import current_platform

distribution_version = version("vllm")
assert ".rocm" in distribution_version, distribution_version
assert distribution_version == os.environ["VLLM_EXPECTED_VERSION"], distribution_version
assert torch.version.hip, "PyTorch is not a ROCm/HIP build"
assert type(current_platform).__name__ == "RocmPlatform", type(current_platform)

device = torch.device("cuda:0")
result = (torch.arange(8, device=device) ** 2).cpu().tolist()
assert result == [0, 1, 4, 9, 16, 25, 36, 49], result

print("vllm", vllm.__version__)
print("vllm_distribution", distribution_version)
print("torch", torch.__version__)
print("hip", torch.version.hip)
print("platform", type(current_platform).__name__)
print("gpu", torch.cuda.get_device_name(0))
print("gpu_tensor_smoke", result)
PY

"$VENV/bin/vllm" --help >/dev/null

{
  date -Is
  echo "status=historical-known-good-requires-current-pod-verification"
  echo "variant=$VLLM_ROCM_VARIANT"
  echo "wheel_commit=$VLLM_WHEEL_COMMIT"
  echo "wheel_url=$VLLM_WHEEL_URL"
  echo "wheel_sha256=$VLLM_WHEEL_SHA256"
  echo "dependency_index=$VLLM_DEPENDENCY_INDEX"
  "$VENV/bin/python" -c \
    'import importlib.metadata, torch; print("vllm=" + importlib.metadata.version("vllm")); print("torch=" + torch.__version__); print("hip=" + str(torch.version.hip))'
} > "$LOG_DIR/vllm-install-manifest.txt"
"$UV" pip freeze --python "$VENV/bin/python" > "$LOG_DIR/vllm-install-freeze.txt"

echo "IMPORTANT: review $LOG_DIR/vllm-install-freeze.txt after the real W7900 gate."
echo "Commit a reviewed dependency lock only after the 14B load and tool-call checks pass."

echo "vLLM environment installed."
echo "Activate with: source $VENV/bin/activate"
