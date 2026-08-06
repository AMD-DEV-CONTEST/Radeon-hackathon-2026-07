from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.realtime_agent_orchestration import (
    compile_realtime_creative_council,
)


ROOT = Path(__file__).resolve().parents[1]


class RealtimeAgentOrchestrationTests(unittest.TestCase):
    def test_graph_loop_harness_is_observable_and_fail_closed(self) -> None:
        brief = json.loads(
            (ROOT / "config/frontier-gtm-brief-b2b-frozen.json").read_text(
                encoding="utf-8"
            )
        )
        council = compile_realtime_creative_council(
            brief,
            primary_platform="linkedin",
            secondary_platform="youtube",
        )
        self.assertEqual(
            council["graph"],
            [
                "market-diagnosis",
                "strategy-debate",
                "platform-language",
                "multimodal-direction",
                "adversarial-cut",
                "release-harness",
            ],
        )
        self.assertEqual([row["order"] for row in council["node_receipts"]], list(range(1, 7)))
        self.assertTrue(all(row["tool_execution_observed"] for row in council["node_receipts"]))
        self.assertTrue(all(not row["external_action_executed"] for row in council["node_receipts"]))
        self.assertTrue(council["harness"]["generic_copy_fallback_allowed"] is False)
        self.assertTrue(council["harness"]["same_formula_across_industries_forbidden"])
        self.assertTrue(council["harness"]["named_human_release_required"])
        self.assertFalse(council["harness"]["automatic_publish_send_spend"])

    def test_finalists_are_not_template_recolors(self) -> None:
        brief = json.loads(
            (ROOT / "config/frontier-gtm-brief-b2c-frozen.json").read_text(
                encoding="utf-8"
            )
        )
        council = compile_realtime_creative_council(
            brief,
            primary_platform="instagram",
            secondary_platform="tiktok",
        )
        territories = council["territories"]
        self.assertEqual(len(territories), 3)
        for axis in ("hook", "narrative", "visual", "tone"):
            self.assertEqual(
                len({territory["axis_signature"][axis] for territory in territories}),
                3,
                axis,
            )
        self.assertEqual(len({territory["campaign_name"] for territory in territories}), 3)
        self.assertEqual(len({territory["first_line"] for territory in territories}), 3)
        self.assertTrue(all(row["axis_distance"] >= 4 for row in council["finalist_axis_distances"]))
        self.assertEqual(council["selection_mode"], "declared_context_fit_score_not_creative_winner")
        self.assertEqual(len(council["selection_scorecards"]), 3)
        self.assertTrue(all(row["creative_preference_claimed"] is False for row in council["selection_scorecards"]))


if __name__ == "__main__":
    unittest.main()
