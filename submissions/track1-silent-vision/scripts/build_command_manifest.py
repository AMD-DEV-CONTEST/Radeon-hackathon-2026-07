#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from command.dataset import build_dataset_manifests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("command/phrase_catalog.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--allow-small-dataset", action="store_true")
    args = parser.parse_args()
    inventory = build_dataset_manifests(
        args.profile_root, args.catalog, args.output_dir, args.allow_small_dataset, args.seed
    )
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
