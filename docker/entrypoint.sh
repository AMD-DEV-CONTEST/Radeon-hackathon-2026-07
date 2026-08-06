#!/usr/bin/env bash
# =============================================================================
# Container entrypoint: ensure model weights are present, then exec the command.
#
# - smolvla_base   : downloaded from HuggingFace hub
#   (repo: lerobot/smolvla_base)
# - Qwen3-VL-8B    : downloaded from ModelScope
#   (model id: Qwen/Qwen3-VL-8B-Instruct)
#
# Offline note: if no network at runtime, mount the weights with
#   -v /host/models:/opt/models
# and set HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1.
# =============================================================================
set -euo pipefail

MODELS_DIR="${SMOLVLA_BASE}"
QWEN_DIR="${QWEN3VL_PATH}"

if [[ ! -f "${SMOLVLA_BASE}/model.safetensors" ]]; then
  echo "[entrypoint] Downloading SmolVLA base weights -> ${SMOLVLA_BASE}"
  HF_HUB_ENABLE_HF_TRANSFER=1 python - <<'PY'
import os, huggingface_hub
from huggingface_hub import snapshot_download
path = snapshot_download("lerobot/smolvla_base", local_dir=os.environ["SMOLVLA_BASE"])
print(f"[entrypoint] SmolVLA base downloaded: {path}")
PY
else
  echo "[entrypoint] SmolVLA base weights present (${SMOLVLA_BASE})"
fi

if [[ ! -d "${QWEN3VL_PATH}" || -z "$(ls -A "${QWEN3VL_PATH}" 2>/dev/null)" ]]; then
  echo "[entrypoint] Downloading Qwen3-VL-8B via ModelScope -> ${QWEN3VL_PATH}"
  python - <<'PY'
import os, modelscope
from modelscope import snapshot_download
path = snapshot_download("Qwen/Qwen3-VL-8B-Instruct", local_dir=os.environ["QWEN3VL_PATH"])
print(f"[entrypoint] Qwen3-VL downloaded: {path}")
PY
else
  echo "[entrypoint] Qwen3-VL weights present (${QWEN3VL_PATH})"
fi

echo "[entrypoint] Executing: $*"
exec "$@"
