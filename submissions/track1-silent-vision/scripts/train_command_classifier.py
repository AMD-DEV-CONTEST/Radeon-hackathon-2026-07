#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the fixed-phrase classifier on ROCm"
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("command/phrase_catalog.json")
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--train-manifest", type=Path, required=True)
    parser.add_argument("--calibration-known", type=Path, required=True)
    parser.add_argument("--calibration-unknown", type=Path, required=True)
    parser.add_argument("--evaluation-known", type=Path, required=True)
    parser.add_argument("--evaluation-unknown", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-summary", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int, default=17)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    from command.training import train_phrase_classifier

    summary = train_phrase_classifier(
        catalog_path=args.catalog,
        inventory_path=args.inventory,
        train_manifest=args.train_manifest,
        calibration_known_manifest=args.calibration_known,
        calibration_unknown_manifest=args.calibration_unknown,
        evaluation_known_manifest=args.evaluation_known,
        evaluation_unknown_manifest=args.evaluation_unknown,
        output_path=args.output,
        run_summary_path=args.run_summary,
        epochs=args.epochs,
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
