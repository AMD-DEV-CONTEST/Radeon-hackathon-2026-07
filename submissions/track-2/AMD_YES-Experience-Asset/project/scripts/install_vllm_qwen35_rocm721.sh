#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
VENV="${VLLM_VENV:-$ROOT/venvs/vllm-026-qwen35}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$(dirname "$SCRIPT_DIR")}"
PIN_FILE="$REPO/config/runtime/vllm-rocm721-qwen35.env"
WHEEL_CACHE="${VLLM_WHEEL_CACHE:-$ROOT/cache/wheels}"

if [[ "$ROOT" != /workspace/* ]]; then
  echo "ERROR: keep the isolated runtime under persistent /workspace."
  exit 1
fi
if [[ ! -f "$PIN_FILE" ]]; then
  echo "ERROR: frozen Qwen3.5 vLLM pin file not found: $PIN_FILE"
  exit 1
fi
# shellcheck disable=SC1090
source "$PIN_FILE"
: "${VLLM_EXPECTED_VERSION:?}"
: "${VLLM_WHEEL_URL:?}"
: "${VLLM_WHEEL_SHA256:?}"
: "${VLLM_DEPENDENCY_INDEX:?}"

mkdir -p "$WHEEL_CACHE"
wheel_filename="$(python3 -c 'import os,sys,urllib.parse; print(urllib.parse.unquote(os.path.basename(sys.argv[1])))' "$VLLM_WHEEL_URL")"
wheel_path="$WHEEL_CACHE/$wheel_filename"
if [[ -f "$wheel_path" ]] && ! echo "$VLLM_WHEEL_SHA256  $wheel_path" | sha256sum --check --status; then
  echo "WARN: removing cached vLLM wheel with the wrong SHA-256: $wheel_path"
  rm -f "$wheel_path"
fi
if [[ ! -f "$wheel_path" ]]; then
  curl -fL --retry 3 --retry-delay 2 --output "$wheel_path.part" "$VLLM_WHEEL_URL"
  echo "$VLLM_WHEEL_SHA256  $wheel_path.part" | sha256sum --check --status || {
    rm -f "$wheel_path.part"
    echo "ERROR: downloaded vLLM wheel failed SHA-256 verification."
    exit 1
  }
  mv "$wheel_path.part" "$wheel_path"
fi
echo "$VLLM_WHEEL_SHA256  $wheel_path" | sha256sum --check --status

if [[ -x "$ROOT/venvs/vllm/bin/uv" ]]; then
  UV="$ROOT/venvs/vllm/bin/uv"
elif command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
else
  [[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip uv
  UV="$VENV/bin/uv"
fi
[[ -x "$VENV/bin/python" ]] || "$UV" venv "$VENV" --python 3.12 --seed
"$VENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
UV_LINK_MODE=copy "$UV" pip install --python "$VENV/bin/python" --pre --upgrade \
  "$wheel_path" \
  --extra-index-url "$VLLM_DEPENDENCY_INDEX" \
  --index-strategy unsafe-best-match

VLLM_EXPECTED_VERSION="$VLLM_EXPECTED_VERSION" "$VENV/bin/python" - <<'PY'
import os
from importlib.metadata import version

import torch
from vllm.platforms import current_platform

assert version("vllm") == os.environ["VLLM_EXPECTED_VERSION"], version("vllm")
assert torch.version.hip, torch.__version__
assert type(current_platform).__name__ == "RocmPlatform", type(current_platform)
values = (torch.arange(8, device="cuda:0") ** 2).cpu().tolist()
assert values == [0, 1, 4, 9, 16, 25, 36, 49], values
print("vllm", version("vllm"))
print("torch", torch.__version__)
print("hip", torch.version.hip)
print("platform", type(current_platform).__name__)
print("gpu", torch.cuda.get_device_name(0))
print("gpu_tensor_smoke", values)
PY

"$VENV/bin/vllm" --help >/dev/null
echo "Qwen3.5 isolated vLLM runtime installed at $VENV"
