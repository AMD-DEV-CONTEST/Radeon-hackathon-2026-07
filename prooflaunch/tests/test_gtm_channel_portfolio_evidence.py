from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.compile_gtm_channel_portfolio_matrix import build_matrix


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/channel-portfolio-matrix.json"


class ChannelPortfolioMatrixEvidenceTests(unittest.TestCase):
    def test_sealed_matrix_matches_the_current_compiler_byte_for_byte(self) -> None:
        self.assertTrue(EVIDENCE.is_file())
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed, build_matrix())

    def test_matrix_has_all_48_scenarios_and_no_automatic_activation(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed["scenario_count"], 48)
        self.assertEqual(len(sealed["cases"]), 48)
        self.assertTrue(
            all(case["governed_route_count"] == 12 for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["external_activation_executed"] is False for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["calendar_slot_count"] == 7 for case in sealed["cases"])
        )
        self.assertEqual(
            {case["schedule_timezone"] for case in sealed["cases"]},
            {"UTC", "America/New_York", "Asia/Tokyo", "Europe/London"},
        )
        self.assertTrue(
            all(len(case["content_calendar_sha256"]) == 64 for case in sealed["cases"])
        )
        self.assertEqual(
            {case["breakout_archetype"] for case in sealed["cases"]},
            {
                "founder_learning_relay",
                "peer_proof_transfer",
                "search_evidence_compound",
                "customer_decision_relay",
                "community_language_loop",
                "utility_demo_remix",
                "search_video_compound",
                "customer_ritual_loop",
            },
        )
        self.assertTrue(
            all(
                case["breakout_step_ids"]
                == ["sense", "make", "seed", "convert", "learn"]
                for case in sealed["cases"]
            )
        )
        self.assertTrue(
            all(case["breakout_paid_independent_core"] is True for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["breakout_external_action_performed"] is False for case in sealed["cases"])
        )
        self.assertTrue(
            all(len(case["breakout_growth_loop_sha256"]) == 64 for case in sealed["cases"])
        )
        self.assertTrue(
            all(len(case["text_challenger_plan_sha256"]) == 64 for case in sealed["cases"])
        )
        self.assertTrue(
            all(
                case["text_challenger_territory_ids"]
                == ["decision_xray", "proof_before_promise", "voluntary_relay"]
                for case in sealed["cases"]
            )
        )
        self.assertTrue(
            all(case["text_challenger_official_first_required"] is True for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["text_challenger_maximum_model_calls"] == 3 for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["text_challenger_execution_mode"] == "sequential_fail_fast" for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["text_challenger_maximum_concurrency"] == 1 for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["text_challenger_default_retry_rounds"] == 0 for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["text_challenger_winner_selected"] is False for case in sealed["cases"])
        )
        self.assertTrue(
            all(case["text_challenger_external_publish_executed"] is False for case in sealed["cases"])
        )
        zero_budget = [case for case in sealed["cases"] if case["budget"] == "zero"]
        self.assertTrue(zero_budget)
        self.assertTrue(
            all(
                set(case["excluded_channels"]) == {"paid_search", "paid_social"}
                for case in zero_budget
            )
        )
        self.assertTrue(
            all(case["breakout_paid_amplifier_channel"] is None for case in zero_budget)
        )

    def test_evidence_digest_covers_every_case(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        supplied = sealed.pop("content_sha256")
        encoded = json.dumps(
            sealed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(supplied, hashlib.sha256(encoded.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    unittest.main()
