from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_gold_human_review import aggregate_completed_reviews  # noqa: E402


def _read(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    root = ROOT / "data/v10_gold_human_review"
    cases = _read(root / "blind-cases.jsonl")
    reviews: list[dict[str, object]] = []
    review_dir = root / "completed-reviews"
    if review_dir.is_dir():
        for path in sorted(review_dir.glob("reviewer-*.jsonl")):
            reviews.extend(_read(path))
    aggregate = aggregate_completed_reviews(cases, reviews)
    if aggregate["promotion_passed"]:
        status = "passed_five_human_gold_review"
    elif aggregate["review_set_complete"]:
        status = "failed_complete_human_review_below_promotion_gate"
    else:
        status = "not_observed_incomplete_human_review"
    report = {
        "schema": "ProofLaunchFiveHumanGoldReviewGateV1",
        "status": status,
        **aggregate,
        "human_review_claim_allowed": aggregate["review_set_complete"],
        "gold_mean_4_7_claim_allowed": aggregate["promotion_passed"],
        "model_generated_review_count": 0,
        "truth_boundary": "Only completed, attested, hash-bound human rows count. No score is imputed for missing reviewers or cases.",
    }
    output = ROOT / "evidence/v10/gold-five-human-review-gate.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if aggregate["promotion_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
