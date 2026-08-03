#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${STAGEPOSTER_ROOT:-/workspace/poster-engine}"
VLLM_VENV="${VLLM_VENV:-$ROOT/.venv-vllm}"
VLLM_PYTHON="${VLLM_PYTHON:-3.12.3}"
VLLM_ROCM_INDEX="${VLLM_ROCM_INDEX:-https://wheels.vllm.ai/rocm/}"
VLLM_VERSION="${VLLM_VERSION:-}"

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi

  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
}

install_uv

uv python install "$VLLM_PYTHON"

if [[ ! -x "$VLLM_VENV/bin/python" ]]; then
  uv venv \
    --python "$VLLM_PYTHON" \
    "$VLLM_VENV"
fi

PACKAGE="vllm"

if [[ -n "$VLLM_VERSION" ]]; then
  PACKAGE="vllm==$VLLM_VERSION"
fi

uv pip install \
  --python "$VLLM_VENV/bin/python" \
  --extra-index-url "$VLLM_ROCM_INDEX" \
  "$PACKAGE"

uv pip install \
  --python "$VLLM_VENV/bin/python" \
  "huggingface_hub[cli]"

echo
echo "vLLM environment installed."

"$VLLM_VENV/bin/python" --version

"$VLLM_VENV/bin/python" - <<'PY'
import importlib.metadata
for name in ("vllm", "torch", "transformers", "huggingface_hub"):
    try:
        print(f"{name}: {importlib.metadata.version(name)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{name}: not installed")
PY
