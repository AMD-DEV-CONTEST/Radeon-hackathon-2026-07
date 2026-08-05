#!/usr/bin/env python3
"""Apply per-tool overrides to factory scaffolds + repack submission.tar.gz.

For each entry in corpus/programbench/per_tool_overrides/<tool>/main.py,
this:
  1. Finds the corresponding factory scaffold at
     T:/determinex-programbench/determinex_pb_factory_<tool>_v1/<tool>/
  2. Overwrites source/main.py with the override
  3. Re-packs submission.tar.gz with the new main.py

Run after generate_mass_overrides.py or smart_mass_overrides.py.
"""

from __future__ import annotations

import argparse
import io
import stat
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"


def find_scaffold_dir(tool_key: str) -> Path | None:
    """Locate the scaffold dir for a tool_key like 'burntsushi__ripgrep.3b7fd44'."""
    direct = EVAL_ROOT / f"determinex_pb_factory_{tool_key}_v1" / tool_key
    if direct.exists():
        return direct
    matches = list(EVAL_ROOT.glob(f"determinex_pb_*_v*/{tool_key}"))
    if matches:
        return matches[0]
    return None


def repack_submission(scaffold_dir: Path) -> bool:
    src_dir = scaffold_dir / "source"
    if not src_dir.is_dir():
        return False
    main_py = src_dir / "main.py"
    compile_sh = src_dir / "compile.sh"
    if not main_py.is_file() or not compile_sh.is_file():
        return False
    tar_path = scaffold_dir / "submission.tar.gz"
    with tarfile.open(tar_path, "w:gz", compresslevel=9) as tar:
        for name, path in (("main.py", main_py), ("compile.sh", compile_sh)):
            data = path.read_bytes()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o755 if name == "compile.sh" else 0o644
            tar.addfile(info, io.BytesIO(data))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-slug", default="", help="substring filter")
    args = ap.parse_args()

    overrides = list(OVERRIDES_DIR.iterdir())
    print(f"Override dirs available: {len(overrides)}")

    applied = 0
    missing_scaffold = 0
    skipped_filter = 0
    for sub in overrides:
        if not sub.is_dir():
            continue
        tool_key = sub.name
        if args.only_slug and args.only_slug not in tool_key:
            skipped_filter += 1
            continue
        ov = sub / "main.py"
        if not ov.is_file():
            continue
        scaffold = find_scaffold_dir(tool_key)
        if not scaffold:
            missing_scaffold += 1
            continue
        target = scaffold / "source" / "main.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ov.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        # Make compile.sh executable if it isn't
        cs = scaffold / "source" / "compile.sh"
        if cs.is_file():
            try:
                cs.chmod(cs.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except Exception:
                pass
        if repack_submission(scaffold):
            applied += 1

    print(f"applied: {applied}")
    print(f"missing scaffold (no factory dir): {missing_scaffold}")
    if args.only_slug:
        print(f"skipped by filter: {skipped_filter}")


if __name__ == "__main__":
    main()
