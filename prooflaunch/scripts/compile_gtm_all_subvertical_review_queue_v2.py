from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_review_queue_v2 import (
    build_all_subvertical_review_queue,
    verify_all_subvertical_review_queue,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile a zero-credit review queue for one targeted lead wave.")
    parser.add_argument(
        "--discovery",
        default=str(ROOT / "evidence/v10/gtm-all-subvertical-discovery-v2.json"),
    )
    parser.add_argument(
        "--capture",
        default=str(ROOT / "evidence/v10/gtm-all-subvertical-wave1-public-capture-v2.json"),
    )
    parser.add_argument(
        "--source-origin",
        default="data/gtm_case_funnel_v2/all-subvertical-public-leads-wave1-v2.json",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-all-subvertical-review-queue-v2.json"),
    )
    return parser.parse_args()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    payload = build_all_subvertical_review_queue(
        _load(Path(args.discovery)),
        _load(Path(args.capture)),
        source_origin=args.source_origin,
    )
    verify_all_subvertical_review_queue(payload)
    output = Path(args.output)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "review_item_count": payload["review_item_count"],
        "machine_ready_for_named_review_count": payload["machine_ready_for_named_review_count"],
        "evidence_gap_count": payload["evidence_gap_count"],
        "observed_named_human_review_count": payload["observed_named_human_review_count"],
        "formal_candidate_quota_credit": payload["formal_candidate_quota_credit"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
