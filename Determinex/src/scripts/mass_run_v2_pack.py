#!/usr/bin/env python3
"""Package every <instance>/source/ into <instance>/submission.tar.gz.

Run after mass_run_v2_scaffold.py and before any eval. Re-run after each
iteration to refresh the tarballs (eval is keyed on submission sha).
"""

from __future__ import annotations

import os
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(
    os.environ.get(
        "DETERMINEX_PB_SCAFFOLD_OUT",
        "T:/determinex-programbench/mass_run_v2_base",
    )
)


def pack_one(inst_dir: Path) -> Path | None:
    source = inst_dir / "source"
    if not source.is_dir():
        return None
    sub = inst_dir / "submission.tar.gz"
    now = int(time.time())
    with tarfile.open(sub, "w:gz", compresslevel=6) as tf:
        for p in sorted(source.rglob("*")):
            if not p.is_file():
                continue
            ti = tf.gettarinfo(str(p), arcname=str(p.relative_to(source)).replace("\\", "/"))
            ti.mtime = now  # current time so cargo sees source as newer than any cached binary
            ti.uid = 0
            ti.gid = 0
            ti.uname = ""
            ti.gname = ""
            if ti.name.endswith(".sh") or ti.name == "executable" or ti.name.endswith(".py"):
                ti.mode = 0o755
            else:
                ti.mode = 0o644
            with p.open("rb") as f:
                tf.addfile(ti, f)
    return sub


def main():
    if not ROOT.is_dir():
        sys.exit(f"missing: {ROOT}")
    instance_dirs = [p for p in sorted(ROOT.iterdir()) if p.is_dir() and p.name != "__pycache__"]
    n_packed = 0
    for d in instance_dirs:
        out = pack_one(d)
        if out:
            n_packed += 1
    print(f"[pack] {n_packed}/{len(instance_dirs)} submissions packaged under {ROOT}")


if __name__ == "__main__":
    main()
