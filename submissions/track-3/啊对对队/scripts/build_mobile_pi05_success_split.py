#!/usr/bin/env python3
"""Freeze the verified 1,500-episode parcel dataset split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_success_split import build_mobile_success_split


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-summary", type=Path, required=True)
    parser.add_argument("--dataset-info", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260729)
    args = parser.parse_args()
    payload = build_mobile_success_split(
        collection_summary=args.collection_summary,
        dataset_info=args.dataset_info,
        output=args.output,
        seed=args.seed,
    )
    print(json.dumps(payload["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
