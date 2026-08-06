#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.campaign_pack_blind_review import (
    compile_campaign_pack_blind_review_bundle,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        default=str(ROOT / "artifacts/campaign-pack-visual-blind-review-v1"),
    )
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--left-manifest")
    parser.add_argument("--right-manifest")
    args = parser.parse_args()
    if bool(args.left_manifest) != bool(args.right_manifest):
        parser.error("--left-manifest and --right-manifest must be provided together")
    result = compile_campaign_pack_blind_review_bundle(
        ROOT,
        args.output_root,
        seed=args.seed,
        candidate_manifest_paths=(args.left_manifest, args.right_manifest)
        if args.left_manifest
        else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
