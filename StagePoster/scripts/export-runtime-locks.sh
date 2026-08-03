#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

PROJECT_ROOT="$BACKEND_ROOT"
ENV_FILE="${ENV_FILE:-}"

# Support both backend/.env (legacy) and project root .env
if [[ -z "$ENV_FILE" ]]; then
  if [[ -f "$BACKEND_ROOT/.env" ]]; then
    ENV_FILE="$BACKEND_ROOT/.env"
  elif [[ -f "$PROJECT_ROOT/.env" ]]; then
    ENV_FILE="$PROJECT_ROOT/.env"
  fi
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

ROOT="${STAGEPOSTER_ROOT:-/workspace/poster-engine}"
COMFY_ROOT="${COMFY_ROOT:-$ROOT/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-$ROOT/venv}"
VLLM_VENV="${VLLM_VENV:-$ROOT/.venv-vllm}"

mkdir -p "$BACKEND_ROOT/locks"

"$COMFY_VENV/bin/pip" freeze \
  > "$BACKEND_ROOT/locks/comfyui-pip-freeze.txt"

"$VLLM_VENV/bin/pip" freeze \
  > "$BACKEND_ROOT/locks/vllm-pip-freeze.txt"

{
  echo "SYSTEM"
  cat /etc/os-release
  uname -a

  echo
  echo "GPU"
  rocm-smi --showproductname || true
  rocminfo | grep -m1 -E 'Name:.*gfx' || true
  hipcc --version || true

  echo
  echo "GO"
  go version

  echo
  echo "COMFYUI"
  "$COMFY_VENV/bin/python" --version
  git -C "$COMFY_ROOT" rev-parse HEAD || true

  "$COMFY_VENV/bin/python" - <<'PY'
import importlib.metadata
for name in ("torch", "torchvision", "torchaudio"):
    try:
        print(f"{name}: {importlib.metadata.version(name)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{name}: not installed")
PY

  echo
  echo "VLLM"
  "$VLLM_VENV/bin/python" --version

  "$VLLM_VENV/bin/python" - <<'PY'
import importlib.metadata
for name in ("vllm", "torch", "transformers", "huggingface_hub"):
    try:
        print(f"{name}: {importlib.metadata.version(name)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{name}: not installed")
PY
} > "$BACKEND_ROOT/locks/runtime-versions.txt"

echo "Runtime lock reports written to:"
find "$BACKEND_ROOT/locks" -maxdepth 1 -type f -print
