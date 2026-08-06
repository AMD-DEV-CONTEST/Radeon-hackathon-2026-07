from __future__ import annotations

import unittest
import json
from pathlib import Path

from prooflaunch_remix.gtm_organic_breakout_admission import (
    OrganicBreakoutAdmissionError,
    compile_organic_breakout_admissions,
    verify_organic_breakout_admissions,
)
from scripts.compile_gtm_organic_breakout_admissions import (
    build_receipt,
    render_markdown,
)


ROOT = Path(__file__).resolve().parents[1]


def source_records() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(10):
        rows.append(
            {
                "id": f"item-{index}",
                "webpage_url": f"https://social.example/@account/post/{index}",
                "timestamp": 1785542400 - index * 3600,
                "view_count": 5000 if index == 0 else 100,
                "like_count": 500 if index == 0 else 10,
                "comment_count": 50 if index == 0 else 1,
                "title": "A product demonstration" if index == 0 else "Routine update",
            }
        )
    return rows


class OrganicBreakoutAdmissionTests(unittest.TestCase):
    def test_sealed_repository_receipt_matches_compiler(self) -> None:
        receipt = build_receipt()
        self.assertEqual(
            receipt,
            json.loads(
                (ROOT / "evidence/v10/gtm-organic-breakout-admission-v1.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        self.assertEqual(
            render_markdown(receipt),
            (ROOT / "docs/product/GTM_ORGANIC_BREAKOUT_ADMISSION_V1.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_recent_relative_candidate_is_sealed_but_not_promoted(self) -> None:
        receipt = compile_organic_breakout_admissions(
            [
                {
                    "source_id": "source-001",
                    "capture_sha256": "b" * 64,
                    "records": source_records(),
                }
            ],
            observed_at="2026-08-05T00:00:00Z",
        )
        verify_organic_breakout_admissions(receipt)
        self.assertEqual(receipt["admitted_candidate_count"], 1)
        candidate = receipt["candidates"][0]
        self.assertGreater(candidate["relative_attention"], 2)
        self.assertFalse(candidate["raw_expression_retained"])
        self.assertFalse(candidate["causal_growth_claim_allowed"])
        self.assertFalse(candidate["training_admitted"])
        self.assertEqual(receipt["automatic_learning_memory_write_count"], 0)

    def test_giveaway_is_rejected_as_pseudo_breakout(self) -> None:
        rows = source_records()
        rows[0]["title"] = "Giveaway: win a free product"
        receipt = compile_organic_breakout_admissions(
            [
                {
                    "source_id": "source-001",
                    "capture_sha256": "c" * 64,
                    "records": rows,
                }
            ],
            observed_at="2026-08-05T00:00:00Z",
        )
        self.assertEqual(receipt["admitted_candidate_count"], 0)
        self.assertEqual(
            receipt["rejected_finding_counts"]["pseudo_breakout_signal_detected"],
            1,
        )

    def test_tampered_receipt_fails(self) -> None:
        receipt = compile_organic_breakout_admissions(
            [
                {
                    "source_id": "source-001",
                    "capture_sha256": "d" * 64,
                    "records": source_records(),
                }
            ],
            observed_at="2026-08-05T00:00:00Z",
        )
        receipt["admitted_candidate_count"] = 99
        with self.assertRaisesRegex(OrganicBreakoutAdmissionError, "seal"):
            verify_organic_breakout_admissions(receipt)


if __name__ == "__main__":
    unittest.main()
