#!/usr/bin/env python3
"""Migrate mutable project data into Radeon Cloud /workspace/persistence.

Official notice (2026-07): persistent storage directory is now
  /workspace/persistence

This script copies existing local `data/` runtime artifacts into:
  /workspace/persistence/PrivateLocalAgent/data/...

Sample docs stay in the git checkout and are not moved.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import (  # noqa: E402
    DEFAULT_CLOUD_DATA_ROOT,
    DEFAULT_PERSISTENCE_BASE,
    detect_data_root,
)

# Mutable trees to migrate (relative to a data/ root).
MIGRATE_REL = [
    "vector_store",
    "memory",
    "uploads",
    "generated_projects",
    "workflows",
    "app_configs",
    "exports",
]


def _copy_tree(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    copied = 0
    dst.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        if not dst.exists():
            shutil.copy2(src, dst)
            return 1
        return 0
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(path, target)
            copied += 1
    return copied


def main() -> None:
    if not DEFAULT_PERSISTENCE_BASE.is_dir():
        print(f"[skip] {DEFAULT_PERSISTENCE_BASE} not found (not on Radeon Cloud persistence?).")
        print(f"[info] local data_root would be: {detect_data_root()}")
        return

    dest_root = Path(os.getenv("PLA_DATA_ROOT", str(DEFAULT_CLOUD_DATA_ROOT))).expanduser()
    dest_root.mkdir(parents=True, exist_ok=True)
    print(f"[dest] {dest_root}")

    # Common legacy locations on older cloud images
    sources = [
        ROOT / "data",
        Path("/workspace/Radeon-hackathon-2026-07/data"),
        Path("/root/Radeon-hackathon-2026-07/data"),
        Path.home() / "Radeon-hackathon-2026-07" / "data",
    ]

    total = 0
    for src_data in sources:
        if not src_data.is_dir():
            continue
        if src_data.resolve() == (dest_root / "data").resolve():
            continue
        print(f"[scan] {src_data}")
        for name in MIGRATE_REL:
            n = _copy_tree(src_data / name, dest_root / "data" / name)
            if n:
                print(f"  + {name}: {n} files")
                total += n

    # Hint HF cache relocation (do not move huge caches automatically)
    hf_hint = DEFAULT_PERSISTENCE_BASE / "huggingface"
    print(f"[hint] set HF_HOME={hf_hint}  (models survive instance reset)")
    print(f"[hint] set PLA_DATA_ROOT={dest_root}")
    print(f"[ok] migrated_files={total}  data_root={detect_data_root()}")


if __name__ == "__main__":
    main()
