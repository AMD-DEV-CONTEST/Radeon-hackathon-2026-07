#!/usr/bin/env bash
set -euo pipefail

# Download the official dense BF16 checkpoint from ModelScope. Hugging Face
# is not required by the RadeonX instance network policy.
MODEL_ID="${MODEL_ID:-Qwen/Qwen3-14B}"
MODEL_DIR="${MODEL_DIR:-/root/models/Qwen3-14B-BF16}"
REVISION="${REVISION:-master}"
PYTHON_BIN="${PYTHON_BIN:-/root/radeon-code-agent-venv/bin/python}"
export MODEL_ID MODEL_DIR REVISION

mkdir -p "${MODEL_DIR}"
if command -v modelscope >/dev/null 2>&1; then
  modelscope download --model "${MODEL_ID}" --revision "${REVISION}" --local_dir "${MODEL_DIR}"
else
  "${PYTHON_BIN}" - <<'PY'
import os
from modelscope import snapshot_download

snapshot_download(
    os.environ.get("MODEL_ID", "Qwen/Qwen3-14B"),
    revision=os.environ.get("REVISION", "master"),
    local_dir=os.environ.get("MODEL_DIR", "/root/models/Qwen3-14B-BF16"),
)
PY
fi

# Exclude the manifest itself so its checksum is stable and reproducible.
find "${MODEL_DIR}" -type f ! -name SHA256SUMS.txt -print0 | sort -z | xargs -0 sha256sum > "${MODEL_DIR}/SHA256SUMS.txt"
printf 'model=%s\nrevision=%s\npath=%s\nmanifest=%s\n' \
  "${MODEL_ID}" "${REVISION}" "${MODEL_DIR}" "${MODEL_DIR}/SHA256SUMS.txt"
