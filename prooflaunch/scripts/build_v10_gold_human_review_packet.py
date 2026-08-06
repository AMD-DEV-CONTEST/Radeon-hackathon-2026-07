from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_gold_human_review import (  # noqa: E402
    ATTESTATION,
    CASE_COUNT,
    EXPECTED_REVIEW_COUNT,
    PROMOTION_MEAN,
    REVIEWER_COUNT,
    RUBRIC_DIMENSIONS,
    blind_case,
    review_template,
)
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def _read(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write(path: Path, rows: list[dict[str, object]]) -> str:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    atomic_write_text(path, text)
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    source = ROOT / "data/v10_gold_candidates"
    output = ROOT / "data/v10_gold_human_review"
    templates = output / "review-templates"
    output.mkdir(parents=True, exist_ok=True)
    templates.mkdir(parents=True, exist_ok=True)
    briefs = _read(source / "brief-candidates.jsonl")
    campaigns = _read(source / "campaign-candidates.jsonl")
    cases = [blind_case(row, "brief") for row in briefs]
    cases.extend(blind_case(row, "campaign") for row in campaigns)
    if len(cases) != CASE_COUNT or len({row["case_id"] for row in cases}) != CASE_COUNT:
        raise RuntimeError("gold human review case count drift")
    cases_sha = _write(output / "blind-cases.jsonl", cases)
    template_hashes: dict[str, str] = {}
    assignment_rows: list[dict[str, object]] = []
    for reviewer_slot in range(1, REVIEWER_COUNT + 1):
        ordered = list(cases)
        random.Random(20_260_731 + reviewer_slot).shuffle(ordered)
        rows = [review_template(case, reviewer_slot) for case in ordered]
        name = f"reviewer-{reviewer_slot:02d}.jsonl"
        template_hashes[name] = _write(templates / name, rows)
        assignment_rows.extend(
            {
                "reviewer_slot": reviewer_slot,
                "ordinal": ordinal,
                "case_id": case["case_id"],
                "case_sha256": case["case_sha256"],
            }
            for ordinal, case in enumerate(ordered, start=1)
        )
    assignment_sha = _write(output / "assignments.jsonl", assignment_rows)
    rubric = {
        "schema": "ProofLaunchFiveHumanGoldReviewRubricV1",
        "reviewer_count": REVIEWER_COUNT,
        "case_count": CASE_COUNT,
        "expected_review_count": EXPECTED_REVIEW_COUNT,
        "dimensions": list(RUBRIC_DIMENSIONS),
        "score_scale": {"1": "unusable", "2": "major rework", "3": "competent", "4": "strong", "5": "exceptional and publishable"},
        "instructions": [
            "Review independently in assigned order.",
            "Judge supplied output, not brand familiarity or presumed model identity.",
            "Use integer or half-point scores from 1 to 5.",
            "Any score below 5 requires a concrete required_rework statement.",
            "Do not use an AI model to generate ratings or comments.",
            "Set publishable=true only when the case can ship without substantive rework.",
            "After completing a row, set review_content_sha256 using the provided verifier.",
        ],
        "attestation_exact_text": ATTESTATION,
        "promotion": {
            "all_2250_reviews_required": True,
            "all_450_cases_need_five_distinct_reviewers": True,
            "mean_score_minimum": PROMOTION_MEAN,
            "each_dimension_mean_minimum": 4.5,
            "publishable_rate_minimum": 0.95,
        },
    }
    rubric["rubric_sha256"] = stable_sha256(rubric)
    atomic_write_text(output / "rubric.json", json.dumps(rubric, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "schema": "ProofLaunchFiveHumanGoldReviewPacketManifestV1",
        "case_count": len(cases),
        "brief_case_count": len(briefs),
        "campaign_case_count": len(campaigns),
        "reviewer_slot_count": REVIEWER_COUNT,
        "assignment_count": len(assignment_rows),
        "reviews_per_case_required": REVIEWER_COUNT,
        "cases_per_reviewer": CASE_COUNT,
        "blind_cases_sha256": cases_sha,
        "assignments_sha256": assignment_sha,
        "template_hashes": template_hashes,
        "rubric_sha256": rubric["rubric_sha256"],
        "source_manifest_sha256": json.loads((source / "manifest.json").read_text(encoding="utf-8"))["manifest_sha256"],
        "source_provider_names_exposed": False,
        "source_urls_exposed": False,
        "human_reviews_observed": 0,
        "mean_score_observed": None,
        "promotion_passed": False,
        "truth_boundary": "This packet makes five-person review executable and independently auditable. Empty templates are not reviews and provide no evidence for TODO 0497 or 0498.",
    }
    manifest["manifest_sha256"] = stable_sha256(manifest)
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "five_person_review_packet_ready_no_reviews", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
