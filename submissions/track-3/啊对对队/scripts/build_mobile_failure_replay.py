#!/usr/bin/env python3
"""Build a curriculum replay manifest from audited mobile collection failures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_harness import build_mobile_failure_replay_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-episode-id", action="append", default=[])
    args = parser.parse_args()

    summary = json.loads(args.collection_summary.read_text(encoding="utf-8"))
    manifest = build_mobile_failure_replay_manifest(
        summary,
        source_summary=str(args.collection_summary.resolve()),
        holdout_episode_ids=args.holdout_episode_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
