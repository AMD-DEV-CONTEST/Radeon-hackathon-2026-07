#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Silent Vision prototype profile sample counts.")
    parser.add_argument("--root", type=Path, default=Path("/workspace/persistent/silent-vision"))
    args = parser.parse_args()

    profiles_dir = args.root / "profiles"
    if not profiles_dir.exists():
        print(f"No profiles found under {profiles_dir}")
        return 0

    profile_dirs = sorted(path for path in profiles_dir.iterdir() if path.is_dir())
    if not profile_dirs:
        print(f"No profiles found under {profiles_dir}")
        return 0

    for profile_dir in profile_dirs:
        print(f"Profile: {profile_dir.name}")
        intent_dirs = sorted(path for path in profile_dir.iterdir() if path.is_dir())
        if not intent_dirs:
            print("  no samples")
            continue
        for intent_dir in intent_dirs:
            count = sum(1 for sample_dir in intent_dir.iterdir() if sample_dir.is_dir())
            print(f"  {intent_dir.name}: {count} samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
