#!/usr/bin/env python3
"""Download all model weights needed to run the ChromaSort-VLA pipeline.

This is used both inside the Docker image (via entrypoint.sh) and on a bare
host before running the pipeline. Two models are fetched:

  1. SmolVLA base  (lerobot/smolvla_base)      -> $SMOLVLA_BASE
  2. Qwen3-VL-8B   (Qwen/Qwen3-VL-8B-Instruct) -> $QWEN3VL_PATH

Usage:
    python download_models.py            # uses default paths under /opt/models
    SMOLVLA_BASE=/mnt/models/smolvla python download_models.py

The Qwen3-VL weights are fetched via ModelScope (huggingface.co is often
unreachable from China-region / Radeon cloud hosts). If your host has HF
access, set USE_HF=1 to pull Qwen3-VL from HuggingFace instead.
"""

from __future__ import annotations

import os
from pathlib import Path

# Defaults mirror the Docker env (docker-compose.yml / Dockerfile).
SMOLVLA_BASE = Path(os.environ.get("SMOLVLA_BASE", "/opt/models/smolvla_base"))
QWEN3VL_PATH = Path(
    os.environ.get(
        "QWEN3VL_PATH",
        "/opt/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master",
    )
)
USE_HF = os.environ.get("USE_HF", "0") == "1"


def download_smolvla_base() -> Path:
    if (SMOLVLA_BASE / "model.safetensors").exists():
        print(f"[download] SmolVLA base already present: {SMOLVLA_BASE}")
        return SMOLVLA_BASE
    print(f"[download] Fetching lerobot/smolvla_base -> {SMOLVLA_BASE}")
    from huggingface_hub import snapshot_download

    return Path(
        snapshot_download("lerobot/smolvla_base", local_dir=str(SMOLVLA_BASE))
    )


def download_qwen3vl() -> Path:
    if QWEN3VL_PATH.is_dir() and any(QWEN3VL_PATH.iterdir()):
        print(f"[download] Qwen3-VL already present: {QWEN3VL_PATH}")
        return QWEN3VL_PATH
    if USE_HF:
        print(f"[download] Fetching Qwen/Qwen3-VL-8B-Instruct (HF) -> {QWEN3VL_PATH}")
        from huggingface_hub import snapshot_download

        return Path(
            snapshot_download(
                "Qwen/Qwen3-VL-8B-Instruct", local_dir=str(QWEN3VL_PATH)
            )
        )
    print(f"[download] Fetching Qwen3-VL-8B via ModelScope -> {QWEN3VL_PATH}")
    from modelscope import snapshot_download

    return Path(
        snapshot_download(
            "Qwen/Qwen3-VL-8B-Instruct", local_dir=str(QWEN3VL_PATH)
        )
    )


def main() -> None:
    download_smolvla_base()
    download_qwen3vl()
    print("[download] All model weights ready.")


if __name__ == "__main__":
    main()
