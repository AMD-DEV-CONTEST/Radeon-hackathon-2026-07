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
from prooflaunch_remix.gtm_platform_craft_review import (  # noqa: E402
    aggregate_platform_craft_reviews,
)


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-packet", required=True, type=_inside_project)
    parser.add_argument("--private-mapping", required=True, type=_inside_project)
    parser.add_argument("--review", required=True, action="append", type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    args = parser.parse_args()
    public = json.loads(args.public_packet.read_text(encoding="utf-8"))
    private = json.loads(args.private_mapping.read_text(encoding="utf-8"))
    reviews = []
    for path in args.review:
        reviews.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    aggregate = aggregate_platform_craft_reviews(
        public_packet=public,
        private_mapping=private,
        reviews=reviews,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "submitted_human_review_count": aggregate["submitted_human_review_count"],
                "review_complete": aggregate["review_complete"],
                "craft_gate_passed_count": aggregate["craft_gate_passed_count"],
                "all_thirteen_craft_gates_passed": aggregate[
                    "all_thirteen_craft_gates_passed"
                ],
                "content_sha256": aggregate["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if aggregate["review_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

