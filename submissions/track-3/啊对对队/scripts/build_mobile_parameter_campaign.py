#!/usr/bin/env python3
"""Freeze a balanced outcome-blind mobile parcel parameter campaign."""

from __future__ import annotations

import argparse
from pathlib import Path

from parcel_sorter.mobile_self_improvement_cycle import (
    build_randomized_mobile_campaign_config,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--episode-prefix", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--trials", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = build_randomized_mobile_campaign_config(
        campaign_id=args.campaign_id,
        episode_prefix=args.episode_prefix,
        split=args.split,
        trials=args.trials,
        seed=args.seed,
    )
    write_json(args.output, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
