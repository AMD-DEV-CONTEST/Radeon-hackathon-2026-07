#!/usr/bin/env python3
"""Summarize closed-loop episodes by physical shape and end-effector class."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parcel_sorter.campaign import aggregate_by_category, catalog_profile_metadata  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate parcel episodes by physical category")
    parser.add_argument("summary", type=Path, help="expert or policy summary JSON")
    parser.add_argument("--catalog", type=Path, default=ROOT / "configs" / "catalog_v2.toml")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    with args.summary.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    episodes = payload.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("summary must contain an episodes list")
    result = aggregate_by_category(episodes, catalog_profile_metadata(args.catalog))
    output = args.output or args.summary.with_name("category-summary.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    for key, row in result["groups"].items():
        print(f"{key}: {row['successes']}/{row['attempts']} success, force_abort={row['force_abort_rate']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
