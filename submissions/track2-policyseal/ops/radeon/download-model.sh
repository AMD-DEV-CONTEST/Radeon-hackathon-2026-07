#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_root"
source ops/radeon/policyseal-env.sh

if [[ ! -x /opt/venv/bin/python ]]; then
  echo "Expected the image-provided Radeon runtime at /opt/venv." >&2
  exit 1
fi

model_dir="${POLICYSEAL_MODEL_DIR:-/workspace/models/Qwen3-8B}"
manifest="${project_root}/ops/radeon/qwen3-8b.sha256"
export POLICYSEAL_MODEL_DOWNLOAD_DIR="$model_dir"

mkdir -p "$model_dir"
/opt/venv/bin/python - <<'PY'
import os

from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="Qwen/Qwen3-8B",
    local_dir=os.environ["POLICYSEAL_MODEL_DOWNLOAD_DIR"],
)
PY

(
  cd "$model_dir"
  sha256sum --check "$manifest"
)

echo "Qwen3-8B is downloaded and matches the PolicySeal SHA-256 manifest."
