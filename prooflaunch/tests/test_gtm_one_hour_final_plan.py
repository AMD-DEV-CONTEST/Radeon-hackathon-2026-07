from __future__ import annotations

import copy
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_one_hour_final_plan import (
    OneHourFinalPlanError,
    compile_one_hour_final_plan,
    load_one_hour_snapshot,
    render_one_hour_html,
    render_one_hour_markdown,
    verify_one_hour_final_plan,
)


ROOT = Path(__file__).resolve().parents[1]


class OneHourFinalPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = load_one_hour_snapshot(ROOT)
        cls.plan = compile_one_hour_final_plan(cls.snapshot)

    def test_plan_covers_exactly_sixty_contiguous_minutes(self) -> None:
        verify_one_hour_final_plan(self.plan)
        rows = self.plan["one_hour_schedule"]
        self.assertEqual(rows[0]["start_minute"], 0)
        self.assertEqual(rows[-1]["end_minute"], 60)
        self.assertEqual(
            sum(row["end_minute"] - row["start_minute"] for row in rows),
            60,
        )

    def test_current_external_truth_cannot_be_promoted(self) -> None:
        decision = self.plan["decision"]
        self.assertTrue(decision["one_hour_submission_freeze_ready"])
        self.assertFalse(decision["named_human_quality_ready"])
        self.assertFalse(decision["named_product_effect_alignment_ready"])
        self.assertFalse(decision["judge_calibration_ready"])
        self.assertFalse(decision["radeon_key_inference_ready"])

    def test_tampered_completion_or_digest_fails_closed(self) -> None:
        tampered = copy.deepcopy(self.plan)
        tampered["decision"]["named_human_quality_ready"] = True
        with self.assertRaises(OneHourFinalPlanError):
            verify_one_hour_final_plan(tampered)

    def test_markdown_and_war_room_expose_truth_boundary(self) -> None:
        markdown = render_one_hour_markdown(self.plan)
        page = render_one_hour_html(self.plan)
        self.assertIn("机械就绪，效果未证", page)
        self.assertIn("一小时终局执行方案", markdown)
        self.assertIn(self.plan["content_sha256"], markdown)
        self.assertIn("First-50", page)


if __name__ == "__main__":
    unittest.main()
