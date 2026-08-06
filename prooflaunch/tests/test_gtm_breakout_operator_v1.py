from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1"


class GTMBreakoutOperatorV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))

    def test_receipt_is_sealed_and_truth_bounded(self) -> None:
        unsigned = dict(self.receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(self.receipt["case_count"], 2)
        self.assertEqual(self.receipt["platform_native_draft_count"], 26)
        self.assertEqual(self.receipt["surface_count_per_case"], 13)
        self.assertEqual([row["platform_native_draft_count"] for row in self.receipt["cases"]], [13, 13])
        self.assertEqual(self.receipt["activated_handoff_role_count"], 12)
        self.assertEqual(self.receipt["craft_context_count"], 144)
        self.assertEqual(self.receipt["territory_handoff_count"], 432)
        self.assertEqual(self.receipt["surface_specialist_lens_assignment_count"], 15552)
        self.assertEqual(self.receipt["unconventional_edge_play_binding_count"], 3888)
        self.assertEqual(self.receipt["maximum_simultaneous_primary_channels_per_case"], 1)
        self.assertEqual(self.receipt["maximum_simultaneous_secondary_channels_per_case"], 1)
        self.assertTrue(self.receipt["remaining_surfaces_held_until_human_approved_signal"])
        self.assertEqual(self.receipt["visible_craft_contract_checks_per_asset"], 4)
        self.assertFalse(self.receipt["numeric_quality_score_present"])
        self.assertEqual(self.receipt["named_product_target_count"], 130)
        self.assertEqual(self.receipt["authorized_named_product_baseline_count"], 7)
        self.assertEqual(self.receipt["source_hidden_five_human_packet_count"], 7)
        self.assertEqual(self.receipt["expected_human_review_count"], 35)
        self.assertEqual(self.receipt["submitted_human_review_count"], 0)
        self.assertEqual(self.receipt["last_mile_copy_ab_expected_human_review_count"], 5)
        self.assertEqual(self.receipt["last_mile_copy_ab_submitted_human_review_count"], 0)
        self.assertEqual(self.receipt["activation_route_count"], 4)
        self.assertEqual(self.receipt["primary_activation_route_count"], 2)
        self.assertEqual(self.receipt["secondary_activation_route_count"], 2)
        self.assertEqual(self.receipt["activation_conversation_reply_count"], 9)
        self.assertEqual(self.receipt["activation_conversion_step_count"], 17)
        self.assertEqual(self.receipt["activation_production_instruction_count"], 10)
        self.assertEqual(self.receipt["activation_finished_asset_count"], 9)
        self.assertEqual(self.receipt["activation_finished_image_count"], 5)
        self.assertEqual(self.receipt["activation_finished_video_count"], 1)
        self.assertEqual(self.receipt["activation_audio_candidate_count"], 3)
        self.assertEqual(self.receipt["activation_release_review_packet_count"], 1)
        self.assertEqual(self.receipt["activation_release_review_expected_human_count"], 5)
        self.assertEqual(self.receipt["activation_release_review_submitted_human_count"], 0)
        self.assertEqual(self.receipt["activation_execution_room_count"], 1)
        self.assertEqual(self.receipt["activation_execution_route_count"], 2)
        self.assertEqual(self.receipt["activation_execution_external_request_count"], 0)
        self.assertEqual(self.receipt["activation_external_execution_count"], 0)
        self.assertEqual(self.receipt["activation_human_release_required_count"], 4)
        self.assertEqual(self.receipt["completed_named_product_pk_count"], 0)
        self.assertEqual(self.receipt["candidate_win_count"], 0)
        self.assertFalse(self.receipt["human_review_completed"])
        self.assertFalse(self.receipt["winner_selected"])
        self.assertFalse(self.receipt["external_publish_executed"])
        self.assertFalse(self.receipt["human_preference_observed"])
        self.assertFalse(self.receipt["organic_breakout_observed"])
        self.assertFalse(self.receipt["conversion_observed"])
        self.assertFalse(self.receipt["revenue_observed"])
        self.assertFalse(self.receipt["named_product_superiority_observed"])

    def test_page_exposes_strategy_work_distribution_and_learning(self) -> None:
        html = (OUTPUT / "index.html").read_text(encoding="utf-8")
        script = (OUTPUT / "operator.js").read_text(encoding="utf-8")
        for marker in (
            "01 / STRATEGY",
            "02 / FINISHED WORK",
            "03 / ACTIVATION WAVE",
            "04 / DISTRIBUTION",
            "05 / LEARNING",
        ):
            self.assertIn(marker, html)
        for phrase in (
            "THE 40-ASSET INTERVIEW",
            "KEEP THE UNPOSTABLE",
            "Don’t ask an AI GTM employee to make 40 launch assets. Ask it which 39 it would refuse to ship.",
            "Your day does not need a documentary to be worth remembering.",
        ):
            self.assertIn(phrase, script)
        self.assertEqual(script.count('"id": "linkedin"'), 2)
        self.assertEqual(script.count('"id": "tiktok"'), 2)
        self.assertIn('renderCase(requestedCase === "b2c" ? "b2c" : "b2b")', script)
        self.assertNotIn('score: "4/4"', script)
        self.assertEqual(script.count('"gate": "PENDING"'), 26)
        self.assertEqual(script.count('"disclosure": "'), 2)
        self.assertIn("SYNTHETIC PRODUCT FIXTURE · NO APP, USER RESULT OR MARKET EFFECT EXISTS", script)
        self.assertIn("PRIMARY / LINKEDIN", script)
        self.assertIn("PRIMARY / TIKTOK", script)
        self.assertIn('data-copy="craft_gate"', html)
        self.assertIn('data-copy="disclosure"', html)
        self.assertIn("Seven real fights.", html)
        self.assertIn("One idea.<br>Thirteen native jobs.", html)
        self.assertIn("The post is only<br>the opening move.", html)
        self.assertIn("no thirteen-channel spray", html)
        self.assertIn("named-product-blind-jury-console-v1/index.html", html)
        self.assertIn("postiz-dry-run-native-preview-v1/index.html", html)
        self.assertIn("keep-unpostable-execution-room-v1/index.html", html)
        self.assertIn("gtm-last-mile-copy-ab-v1/public/reviewer-01.html", html)
        self.assertIn("0/35", html)
        self.assertIn("named-product-pk-openai-image-v1/review-packet/public/reviewer-01.html", html)
        self.assertIn("named-product-pk-qwen-image-v2/review-packet/public/reviewer-01.html", html)
        self.assertIn("named-product-pk-memos-v2/review-packet/public/reviewer-01.html", html)
        self.assertIn("named-product-pk-postiz-v1/review-packet/public/reviewer-01.html", html)
        self.assertIn("Execution first. No imaginary win.", html)
        self.assertEqual(html.count("reviewer-01.html"), 8)
        self.assertEqual(html.count("reviewer-02.html"), 7)
        self.assertEqual(html.count("reviewer-03.html"), 7)
        self.assertEqual(html.count("reviewer-04.html"), 7)
        self.assertEqual(html.count("reviewer-05.html"), 7)

    def test_bound_files_match_receipt(self) -> None:
        for row in self.receipt["artifact_files"] + self.receipt["source_bindings"]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])

    def test_case_system_has_native_depth_without_spray_or_fake_effect(self) -> None:
        case_system = json.loads((OUTPUT / "case-system-v2.json").read_text(encoding="utf-8"))
        unsigned = dict(case_system)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        expected_surfaces = {
            "linkedin", "tiktok", "reddit", "youtube", "instagram", "x",
            "google_search", "bing_search", "chatgpt_answers", "claude_answers",
            "gemini_answers", "perplexity_answers", "copilot_answers",
        }
        self.assertEqual(case_system["platform_native_delivery_count"], 26)
        self.assertEqual(case_system["surface_count_per_case"], 13)
        for case in case_system["cases"].values():
            channels = case["channels"]
            self.assertEqual(len(channels), 13)
            self.assertEqual({row["id"] for row in channels}, expected_surfaces)
            self.assertEqual(len({row["source_candidate_sha256"] for row in channels}), 13)
            for channel in channels:
                self.assertEqual(channel["gate"], "PENDING")
                self.assertIn(channel["activation_role"], {"PRIMARY", "SECONDARY", "RETRIEVAL SUPPORT", "HELD UNTIL SIGNAL"})
                self.assertGreaterEqual(len(channel["lines"]), 4)
                self.assertGreaterEqual(len(channel["notes"]), 5)
                self.assertTrue(channel["cta"])
                self.assertTrue(channel["kill"])
                self.assertTrue(channel["proof"])
                self.assertEqual(channel["measurement"]["activation_state"], "disabled_pending_owner_baseline_and_human_release")
                self.assertFalse(channel["measurement"]["causal_claim_allowed"])
            self.assertEqual(len(case["activation_wave"]), 2)
        activation_routes = [
            route
            for case in case_system["cases"].values()
            for route in case["activation_wave"]
        ]
        self.assertEqual(
            {route["id"] for route in activation_routes},
            {
                "b2b-linkedin-primary",
                "b2b-reddit-secondary",
                "b2c-tiktok-primary",
                "b2c-instagram-secondary",
            },
        )
        for route in activation_routes:
            self.assertTrue(route["human_release_required"])
            self.assertFalse(route["external_execution"])
            self.assertEqual(route["status"], "READY_FOR_HUMAN_RELEASE_REVIEW")
            self.assertGreaterEqual(len(route["conversation_tree"]), 2)
            self.assertGreaterEqual(len(route["conversion_path"]), 4)
            for field in (
                "hypothesis",
                "primary_metric",
                "secondary_metric",
                "baseline_required",
                "test_window",
                "kill_rule",
            ):
                self.assertTrue(route["experiment"][field])
        by_id = {route["id"]: route for route in activation_routes}
        self.assertEqual(len(by_id["b2c-tiktok-primary"]["production_contract"]), 5)
        self.assertEqual(len(by_id["b2c-tiktok-primary"]["production_assets"]), 4)
        self.assertEqual(by_id["b2c-tiktok-primary"]["release_review"]["expected_human_review_count"], 5)
        self.assertEqual(by_id["b2c-tiktok-primary"]["release_review"]["submitted_human_review_count"], 0)
        self.assertEqual(len(by_id["b2c-tiktok-primary"]["release_review"]["reviewer_hrefs"]), 5)
        self.assertEqual(by_id["b2c-tiktok-primary"]["execution_room"]["route_count"], 2)
        self.assertEqual(by_id["b2c-tiktok-primary"]["execution_room"]["external_request_count"], 0)
        self.assertEqual(len(by_id["b2c-instagram-secondary"]["production_contract"]), 5)
        self.assertEqual(len(by_id["b2c-instagram-secondary"]["production_assets"]), 5)
        for asset in (
            by_id["b2c-tiktok-primary"]["production_assets"]
            + by_id["b2c-instagram-secondary"]["production_assets"]
        ):
            self.assertTrue((OUTPUT / asset["href"]).resolve().is_file())
        policy = case_system["activation_policy"]
        self.assertEqual(policy["maximum_simultaneous_primary_channels_per_case"], 1)
        self.assertEqual(policy["maximum_simultaneous_secondary_channels_per_case"], 1)
        self.assertTrue(policy["support_surfaces_are_retrieval_only_until_signal"])
        self.assertTrue(policy["remaining_surfaces_are_held_until_human_approved_signal"])
        self.assertEqual(policy["b2b"]["primary"], "linkedin")
        self.assertEqual(policy["b2b"]["secondary"], "reddit")
        self.assertEqual(policy["b2c"]["primary"], "tiktok")
        self.assertEqual(policy["b2c"]["secondary"], "instagram")
        self.assertEqual(
            {row["id"]: row["activation_role"] for row in case_system["cases"]["b2b"]["channels"]}["linkedin"],
            "PRIMARY",
        )
        self.assertEqual(
            {row["id"]: row["activation_role"] for row in case_system["cases"]["b2c"]["channels"]}["tiktok"],
            "PRIMARY",
        )
        self.assertFalse(case_system["human_review_completed"])
        self.assertFalse(case_system["winner_selected"])
        self.assertFalse(case_system["external_publish_executed"])
        self.assertFalse(case_system["market_effect_observed"])


if __name__ == "__main__":
    unittest.main()
