#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate frozen fixed-phrase thresholds on final partitions"
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--train-manifest", type=Path, required=True)
    parser.add_argument("--calibration-known", type=Path, required=True)
    parser.add_argument("--calibration-unknown", type=Path, required=True)
    parser.add_argument("--known-manifest", type=Path, required=True)
    parser.add_argument("--unknown-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probability-override", type=float, default=None)
    parser.add_argument("--distance-override", type=float, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    from command.evaluation import evaluate_checkpoint

    report = evaluate_checkpoint(
        checkpoint_path=args.checkpoint,
        catalog_path=args.catalog,
        inventory_path=args.inventory,
        train_manifest=args.train_manifest,
        calibration_known_manifest=args.calibration_known,
        calibration_unknown_manifest=args.calibration_unknown,
        known_manifest=args.known_manifest,
        unknown_manifest=args.unknown_manifest,
        output_path=args.output,
        probability_override=args.probability_override,
        distance_override=args.distance_override,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
