#!/usr/bin/env python
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote a personal prototype profile into the global profile.")
    parser.add_argument("--root", type=Path, default=Path("/workspace/persistent/silent-vision"))
    parser.add_argument("--from-profile", required=True, help="Anonymous profileId to copy from")
    args = parser.parse_args()

    source_profile = args.root / "profiles" / args.from_profile
    target_profile = args.root / "profiles" / "global"
    if args.from_profile == "global":
        raise SystemExit("--from-profile must not be global")
    if not source_profile.exists():
        raise SystemExit(f"source profile does not exist: {source_profile}")

    copied = 0
    skipped = 0
    for source_sample in sorted(source_profile.glob("*/*")):
        if not source_sample.is_dir():
            continue
        intent = source_sample.parent.name
        target_sample = target_profile / intent / source_sample.name
        if target_sample.exists():
            skipped += 1
            continue
        target_sample.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_sample, target_sample)
        copied += 1

    print(f"copied {copied} samples from {source_profile} to {target_profile}; skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
