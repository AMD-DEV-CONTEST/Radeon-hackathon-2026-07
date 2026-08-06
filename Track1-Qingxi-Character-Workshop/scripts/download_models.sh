#!/usr/bin/env bash
# Download model weights into the project-local models/ dir (PVC-persisted).
# - LLM -> models/llm
# - Image -> models/image
# Skips each model if it already exists locally, so re-runs are cheap.
# Code loads from models/ first; falls back to HF cache/id if absent.
set -euo pipefail
cd "$(dirname "$0")/.."

python - <<'PY'
from huggingface_hub import snapshot_download
from pathlib import Path
import yaml

cfg = yaml.safe_load(Path("configs/models.yaml").read_text())

def ensure(id_, target):
    target = Path(target)
    # marker files: llm has config.json; diffusers has model_index.json
    marker = target / ("model_index.json" if id_.startswith(("cagliostro", "stabilityai")) else "config.json")
    if target.exists() and marker.exists():
        print(f"SKIP (exists): {id_} -> {target}")
        return
    print(f"DOWNLOAD: {id_} -> {target}")
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(id_, local_dir=str(target))

ensure(cfg["llm"]["model_id"], "models/llm")
ensure(cfg["image"]["model_id"], "models/image")
print("done")
PY
