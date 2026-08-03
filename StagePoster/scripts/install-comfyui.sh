#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${STAGEPOSTER_ROOT:-/workspace/poster-engine}"
COMFY_ROOT="${COMFY_ROOT:-$ROOT/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-$ROOT/venv}"

COMFY_REPOSITORY="${COMFY_REPOSITORY:-https://github.com/Comfy-Org/ComfyUI.git}"
COMFY_COMMIT="${COMFY_COMMIT:-c9602625e445e9ee37d3ac6faf5ea9ec1e0de87e}"
COMFY_PYTHON="${COMFY_PYTHON:-3.10.20}"

AMD_ROCM_WHEEL_INDEX="${AMD_ROCM_WHEEL_INDEX:-https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/}"

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi

  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
}

install_uv

mkdir -p "$ROOT"

if [[ ! -d "$COMFY_ROOT/.git" ]]; then
  git clone "$COMFY_REPOSITORY" "$COMFY_ROOT"
fi

git -C "$COMFY_ROOT" fetch --all --tags
git -C "$COMFY_ROOT" checkout "$COMFY_COMMIT"

uv python install "$COMFY_PYTHON"

if [[ ! -x "$COMFY_VENV/bin/python" ]]; then
  uv venv \
    --python "$COMFY_PYTHON" \
    "$COMFY_VENV"
fi

"$COMFY_VENV/bin/python" -m pip install \
  --upgrade \
  pip \
  setuptools \
  wheel

if [[ "${SKIP_COMFY_TORCH_INSTALL:-0}" != "1" ]]; then
  echo "Installing generic ROCm 7.2 compatible PyTorch wheels."
  echo "The verified AMD image used torch 2.13.0+rocm7.2."
  echo "Set SKIP_COMFY_TORCH_INSTALL=1 when the image already provides that stack."

  "$COMFY_VENV/bin/pip" install \
    torch==2.10.0 \
    torchvision==0.25.0 \
    torchaudio==2.10.0 \
    -f "$AMD_ROCM_WHEEL_INDEX"
fi

"$COMFY_VENV/bin/pip" install \
  -r "$COMFY_ROOT/requirements.txt"

mkdir -p \
  "$COMFY_ROOT/models/diffusion_models" \
  "$COMFY_ROOT/models/text_encoders" \
  "$COMFY_ROOT/models/vae" \
  "$COMFY_ROOT/models/loras"

echo
echo "ComfyUI installed."
"$COMFY_VENV/bin/python" --version
"$COMFY_VENV/bin/python" - <<'PY'
import torch
print("torch:", torch.__version__)
print("HIP:", torch.version.hip)
print("GPU available:", torch.cuda.is_available())
PY
