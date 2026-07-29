#!/usr/bin/env python3
"""One-shot bootstrap for Radeon Cloud / local Windows."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def _setup_cloud_persistence() -> None:
    persist = Path("/workspace/persistence")
    if not persist.is_dir():
        return
    data_root = Path(os.getenv("PLA_DATA_ROOT", str(persist / "PrivateLocalAgent")))
    data_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLA_DATA_ROOT", str(data_root))
    hf = persist / "huggingface"
    hf.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(hf))
    os.environ.setdefault("HF_ENDPOINT", os.getenv("HF_ENDPOINT", "https://hf-mirror.com"))
    print(f"[persistence] PLA_DATA_ROOT={os.environ['PLA_DATA_ROOT']}")
    print(f"[persistence] HF_HOME={os.environ['HF_HOME']}")
    run([sys.executable, str(ROOT / "scripts" / "migrate_to_persistence.py")])
    run([sys.executable, str(ROOT / "scripts" / "backup_to_persistence.py")])


def main() -> None:
    _setup_cloud_persistence()
    run([sys.executable, "-m", "pip", "install", "-U", "pip"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    env = ROOT / ".env"
    if not env.exists():
        env.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example")

    # Prefer local GPU backend when available
    try:
        import torch

        gpu = torch.cuda.is_available()
        print(f"torch.cuda.is_available() = {gpu}")
        cfg = ROOT / "configs" / "default.yaml"
        text = cfg.read_text(encoding="utf-8")
        if gpu:
            text = re.sub(r'backend:\s*".*?"', 'backend: "local_transformers"', text, count=1)
            cfg.write_text(text, encoding="utf-8")
            print("Switched llm.backend -> local_transformers")
    except Exception as exc:  # noqa: BLE001
        print(f"GPU probe skipped: {exc}")

    run([sys.executable, str(ROOT / "scripts" / "verify_rocm.py")])
    run([sys.executable, str(ROOT / "scripts" / "ingest_sample.py")])
    print("Bootstrap done. Start demo with: python app.py")
    print("On Radeon Cloud, keep durable files under /workspace/persistence")


if __name__ == "__main__":
    main()
