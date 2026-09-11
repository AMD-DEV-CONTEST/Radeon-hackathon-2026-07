#!/usr/bin/env python3
"""Build or inspect a frozen, profile-stratified LeRobot split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.dataset_split import (
    build_split_manifest,
    lerobot_episode_argument,
    lerobot_eval_split,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", help="directory containing episodes.jsonl and summary.json")
    parser.add_argument("--dataset-root", help="LeRobot dataset directory")
    parser.add_argument("--output", help="output split manifest JSON")
    parser.add_argument("--seed", type=int, default=20260725)
    parser.add_argument("--validation-fraction", type=float, default=0.10)
    parser.add_argument("--heldout-fraction", type=float, default=0.20)
    parser.add_argument("--manifest", help="existing split manifest for --print")
    parser.add_argument("--print", dest="print_value", choices=("summary", "episodes", "eval_split"))
    args = parser.parse_args()

    if args.print_value:
        if not args.manifest:
            parser.error("--manifest is required with --print")
        if args.print_value == "episodes":
            print(lerobot_episode_argument(args.manifest))
        elif args.print_value == "eval_split":
            print(lerobot_eval_split(args.manifest))
        else:
            payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            print(json.dumps(payload["counts"], ensure_ascii=False, sort_keys=True))
        return 0

    if not args.audit_root or not args.dataset_root or not args.output:
        parser.error("--audit-root, --dataset-root and --output are required to build a split")
    audit_root = Path(args.audit_root)
    dataset_root = Path(args.dataset_root)
    payload = build_split_manifest(
        audit_manifest=audit_root / "episodes.jsonl",
        dataset_info=dataset_root / "meta" / "info.json",
        collection_summary=audit_root.parent / "summary.json",
        output=args.output,
        seed=args.seed,
        validation_fraction=args.validation_fraction,
        heldout_fraction=args.heldout_fraction,
    )
    print(json.dumps(payload["counts"], ensure_ascii=False, sort_keys=True))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
