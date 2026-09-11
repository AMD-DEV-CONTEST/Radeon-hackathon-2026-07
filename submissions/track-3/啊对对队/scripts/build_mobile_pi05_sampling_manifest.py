#!/usr/bin/env python3
"""Build the deterministic parcel PI0.5 training sampling manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_stratified_sampler import build_sampling_manifest_from_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--stage-frame-cap", type=int, default=100)
    args = parser.parse_args()
    payload = build_sampling_manifest_from_dataset(
        dataset_root=args.dataset_root,
        split_manifest_path=args.split_manifest,
        output=args.output,
        seed=args.seed,
        stage_frame_cap_per_episode=args.stage_frame_cap,
    )
    print(
        json.dumps(
            {
                "samples_per_epoch": payload["samples_per_epoch"],
                "samples_per_design_cell_per_epoch": payload[
                    "samples_per_design_cell_per_epoch"
                ],
                "manifest_sha256": payload["manifest_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
