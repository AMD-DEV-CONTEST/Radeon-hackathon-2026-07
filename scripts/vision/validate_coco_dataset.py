"""Validate one real COCO dataset before GPU training."""

from __future__ import annotations

import argparse
from pathlib import Path

from buildguard.evaluation.vision_dataset import audit_coco_dataset
from buildguard.logging_system.jsonl_writer import atomic_write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--content-hash",
        action="store_true",
        help="Hash all images to detect renamed cross-split duplicates.",
    )
    args = parser.parse_args()
    report = audit_coco_dataset(args.root, content_hash=args.content_hash)
    atomic_write_json(args.report, report)
    print(report.model_dump_json(indent=2))
    if report.status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
