#!/usr/bin/env python3
"""Build balanced train-only normalization stats for parcel PI0.5."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_train_stats import build_train_only_normalization_stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--sampling-manifest", type=Path, required=True)
    parser.add_argument("--output-stats", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    args = parser.parse_args()
    payload = build_train_only_normalization_stats(
        dataset_root=args.dataset_root,
        split_manifest_path=args.split_manifest,
        sampling_manifest_path=args.sampling_manifest,
        output_stats=args.output_stats,
        output_manifest=args.output_manifest,
    )
    print(
        json.dumps(
            {
                "normalization_frame_count": payload["normalization_frame_count"],
                "normalization_stats_sha256": payload[
                    "normalization_stats_sha256"
                ],
                "manifest_sha256": payload["manifest_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
