#!/usr/bin/env python3
"""Build the frozen budget-matched competition PI0.5 sampling manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_stratified_sampler import (
    build_competition_sampling_manifest_from_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--samples-per-cell", type=int, default=67)
    parser.add_argument("--progress-bins", type=int, default=5)
    args = parser.parse_args()
    payload = build_competition_sampling_manifest_from_dataset(
        dataset_root=args.dataset_root,
        output=args.output,
        seed=args.seed,
        samples_per_cell=args.samples_per_cell,
        progress_bin_count=args.progress_bins,
    )
    print(
        json.dumps(
            {
                "protocol": payload["protocol"],
                "cell_count": payload["cell_count"],
                "samples_per_epoch": payload["samples_per_epoch"],
                "manifest_sha256": payload["manifest_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
