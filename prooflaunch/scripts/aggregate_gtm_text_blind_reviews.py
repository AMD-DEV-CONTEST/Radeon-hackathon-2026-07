#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_text_challenger_runner import aggregate_text_blind_reviews


def _inside_project(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and deblind thirty completed human text-creative review rows. "
            "The receipt may recommend a territory but never selects or publishes it."
        )
    )
    parser.add_argument("--public-packet", required=True, type=_inside_project)
    parser.add_argument("--private-mapping", required=True, type=_inside_project)
    parser.add_argument("--reviews-jsonl", required=True, type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    args = parser.parse_args()

    public = json.loads(args.public_packet.read_text(encoding="utf-8"))
    private = json.loads(args.private_mapping.read_text(encoding="utf-8"))
    reviews = [
        json.loads(line)
        for line in args.reviews_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    receipt = aggregate_text_blind_reviews(public, private, reviews)
    atomic_write_text(
        args.output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    args.output.chmod(0o600)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "content_sha256": receipt["content_sha256"],
                "review_complete": receipt["review_complete"],
                "recommended_territory_id": receipt["recommended_territory_id"],
                "human_selection_eligible": receipt["human_selection_eligible"],
                "winner_selected": False,
                "external_publish_executed": False,
                "failure_count": receipt["failure_count"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if receipt["review_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
