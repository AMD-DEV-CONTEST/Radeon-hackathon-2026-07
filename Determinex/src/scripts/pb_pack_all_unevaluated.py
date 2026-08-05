#!/usr/bin/env python3
"""Pack tarballs for all per_tool_overrides dirs that have no tarball yet.

Targets board_cache_only tools (never submitted to Hetzner) and any factory_accepted/
near_lock tools whose override directory is newer than the existing tarball.

Output: corpus/programbench/per_tool_overrides/<slug>.tar.gz  (same format used by
        all existing tarballs and the Hetzner eval pipeline).

Usage:
    python scripts/pb_pack_all_unevaluated.py
    python scripts/pb_pack_all_unevaluated.py --status board_cache_only
    python scripts/pb_pack_all_unevaluated.py --slug dirble
    python scripts/pb_pack_all_unevaluated.py --dry-run
    python scripts/pb_pack_all_unevaluated.py --freshen   # also repack stale tarballs
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"

_CRLF_EXTS = {
    ".sh",
    ".py",
    ".bash",
    ".conf",
    ".cfg",
    ".ini",
    ".toml",
    ".yaml",
    ".yml",
    ".txt",
    ".json",
    ".md",
}


def _load_index() -> dict[str, dict]:
    with open(INDEX, encoding="utf-8") as f:
        data = json.load(f)
    return {e["slug"]: e for e in data if not e.get("is_alias") and not e.get("alias_of")}


def _crlf_normalize(b: bytes, ext: str) -> bytes:
    if ext.lower() in _CRLF_EXTS and b"\r\n" in b:
        return b.replace(b"\r\n", b"\n")
    return b


def _pack(override_dir: Path, tarball: Path) -> int:
    """Pack override_dir into tarball using deterministic settings (uid=0, mtime=0).
    Returns number of files packed.
    """
    slug = override_dir.name
    count = 0
    with tarfile.open(str(tarball), "w:gz") as tf:
        for root, dirs, files in os.walk(str(override_dir)):
            dirs.sort()
            for fname in sorted(files):
                fpath = Path(root) / fname
                arcname = slug + "/" + str(fpath.relative_to(override_dir)).replace("\\", "/")
                info = tf.gettarinfo(str(fpath), arcname=arcname)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                # chmod: .sh files get 755, everything else 644
                if fpath.suffix == ".sh" or fpath.name == "executable":
                    info.mode = 0o755
                else:
                    info.mode = 0o644
                ext = fpath.suffix
                raw = fpath.read_bytes()
                normalized = _crlf_normalize(raw, ext)
                info.size = len(normalized)
                tf.addfile(info, io.BytesIO(normalized))
                count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--status",
        default=None,
        help="Only pack tools with this eval_index status (e.g. board_cache_only)",
    )
    ap.add_argument("--slug", default=None, help="Only pack tools whose slug contains this string")
    ap.add_argument(
        "--dry-run", action="store_true", help="Show what would be packed without writing"
    )
    ap.add_argument(
        "--freshen",
        action="store_true",
        help="Also repack tarballs where any compile.sh is newer than the tarball",
    )
    args = ap.parse_args()

    index = _load_index()

    packed = []
    skipped_exists = []
    skipped_no_dir = []
    skipped_status = []
    errors = []

    override_dirs = sorted(OVERRIDES.iterdir()) if OVERRIDES.exists() else []

    for override_dir in override_dirs:
        if not override_dir.is_dir():
            continue
        compile_sh = override_dir / "compile.sh"
        if not compile_sh.exists():
            continue

        slug_dir = override_dir.name  # e.g. isona__dirble.e2dea9f
        tarball = OVERRIDES / (slug_dir + ".tar.gz")

        # Slug filter
        if args.slug and args.slug not in slug_dir:
            continue

        # Status filter — match against eval_index
        if args.status:
            # Find matching entry by slug pattern
            matching = [e for slug, e in index.items() if slug in slug_dir or slug_dir in slug]
            if not matching:
                skipped_status.append(slug_dir)
                continue
            if not any(e.get("status") == args.status for e in matching):
                skipped_status.append(slug_dir)
                continue

        # Check if tarball already exists and is fresh
        if tarball.exists():
            if not args.freshen:
                skipped_exists.append(slug_dir)
                continue
            # Check if any file in override_dir is newer than the tarball
            tar_mtime = tarball.stat().st_mtime
            stale = any(
                (override_dir / f).stat().st_mtime > tar_mtime
                for f in os.listdir(override_dir)
                if (override_dir / f).is_file()
            )
            if not stale:
                skipped_exists.append(slug_dir)
                continue

        if args.dry_run:
            print(f"[DRY] Would pack: {slug_dir}")
            packed.append(slug_dir)
            continue

        try:
            n = _pack(override_dir, tarball)
            size_kb = tarball.stat().st_size // 1024
            print(f"  PACKED {slug_dir} ({n} files, {size_kb}KB) -> {tarball.name}")
            packed.append(slug_dir)
        except Exception as exc:
            print(f"  ERROR {slug_dir}: {exc}", file=sys.stderr)
            errors.append((slug_dir, str(exc)))

    print()
    print("Summary:")
    print(f"  Packed:         {len(packed)}")
    print(f"  Skipped (exists): {len(skipped_exists)}")
    print(f"  Skipped (status): {len(skipped_status)}")
    print(f"  Errors:         {len(errors)}")

    if packed:
        print()
        print("Tarballs ready for Hetzner:")
        for slug_dir in packed:
            print(f"  per_tool_overrides/{slug_dir}.tar.gz")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
