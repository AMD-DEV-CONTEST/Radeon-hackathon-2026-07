#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_codex_lighthouse_human_review import (  # noqa: E402
    aggregate_reviews,
    verify_aggregate,
)


DEFAULT_KIT = ROOT / "artifacts/gtm-last-mile-pk-v1/codex-lighthouse-human-review-kit-v1"
DEFAULT_REVIEWS = ROOT / "data/codex-lighthouse-human-reviews-v1"
DEFAULT_OUTPUT = ROOT / "evidence/v10/gtm-codex-lighthouse-human-review-status-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and aggregate source-hidden Codex lighthouse human reviews.")
    parser.add_argument("--kit", type=Path, default=DEFAULT_KIT)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.reviews.mkdir(parents=True, exist_ok=True)
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(args.reviews.glob("*.json"))
        if path.name != "README.json"
    ]
    aggregate = aggregate_reviews(args.kit.resolve(), payloads)
    verify_aggregate(aggregate)
    atomic_write_text(args.output.resolve(), json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "status": aggregate["status"],
        "submitted_human_review_count": aggregate["submitted_human_review_count"],
        "qualified_candidate_count": aggregate["qualified_candidate_count"],
        "content_sha256": aggregate["content_sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
