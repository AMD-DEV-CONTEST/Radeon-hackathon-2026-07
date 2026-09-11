#!/usr/bin/env python3
"""Audit a LeRobot dataset before training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.data_quality import audit_lerobot_metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit parcel-sorter LeRobot metadata")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--require-depth-rgb", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    root = Path(args.dataset_root)
    info_path = root / "meta" / "info.json"
    stats_path = root / "meta" / "stats.json"
    if not info_path.is_file():
        parser.error(f"LeRobot info metadata not found: {info_path}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.is_file() else None
    audit = audit_lerobot_metadata(
        info,
        stats,
        require_depth_rgb=args.require_depth_rgb,
    )
    payload = audit.to_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    return 0 if audit.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
