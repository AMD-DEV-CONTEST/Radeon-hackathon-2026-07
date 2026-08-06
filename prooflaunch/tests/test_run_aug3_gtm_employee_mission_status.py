from __future__ import annotations

import argparse
import unittest

from scripts.run_aug3_gtm_employee_mission import (
    _craft_failure_summary,
    _critic_failure_allows_human_review_only,
    _mission_status,
    _timeout_seconds,
    _launch_payload,
)


class Aug3GTMEmployeeMissionStatusTests(unittest.TestCase):
    def test_timeout_rejects_before_side_effectful_mission_setup(self) -> None:
        self.assertEqual(_timeout_seconds("120"), 120.0)
        with self.assertRaises(argparse.ArgumentTypeError):
            _timeout_seconds("180")
        with self.assertRaises(argparse.ArgumentTypeError):
            _timeout_seconds("not-a-number")

    def test_b2b_and_b2c_payloads_keep_zero_budget_and_human_release(self) -> None:
        image_sha = "a" * 64
        b2b = _launch_payload(image_sha, scenario="b2b")
        b2c = _launch_payload(image_sha, scenario="b2c")
        self.assertEqual(b2b["strategy"]["business_model"], "b2b")
        self.assertEqual(b2c["strategy"]["business_model"], "b2c")
        self.assertEqual(b2c["strategy"]["lifecycle"], "growth")
        self.assertEqual(b2c["campaign"]["platform"], "TikTok")
        for payload in (b2b, b2c):
            self.assertEqual(payload["maximum_cost_usd"], 0)
            self.assertTrue(payload["human_release_required"])
            self.assertEqual(payload["input_artifacts"]["product_image"], image_sha)

    def test_status_locates_candidate_critic_and_blind_bundle_stages(self) -> None:
        invalid = {"status": "blocked_contract"}
        valid = {"status": "generated_validated_unreviewed"}
        self.assertEqual(_mission_status(invalid, None, None), "blocked_local_candidate_contract")
        self.assertEqual(
            _mission_status(valid, {"all_territories_advisory_pass": False}, None),
            "blocked_local_craft_critic_contract",
        )
        self.assertEqual(
            _mission_status(valid, {"all_territories_advisory_pass": True}, None),
            "blocked_blind_review_bundle_contract",
        )
        self.assertEqual(
            _mission_status(valid, {"all_territories_advisory_pass": True}, {"public_packet": {}}),
            "awaiting_named_human_blind_review",
        )
        self.assertEqual(
            _mission_status(valid, {"all_territories_advisory_pass": False}, {"public_packet": {}}),
            "awaiting_named_human_blind_review_with_critic_contract_failure",
        )

    def test_failure_summary_is_content_free_and_located(self) -> None:
        summary = _craft_failure_summary({
            "records": [
                {"failure": {"error_code": "craft_review_failed", "work_order_id": "review-platform"}},
                {"failure": {"error_code": "craft_review_failed", "work_order_id": "review-claims"}},
                {"status": "advisory_pass"},
            ]
        })
        self.assertEqual(summary["failure_count"], 2)
        self.assertEqual(summary["error_codes"], ["craft_review_failed"])
        self.assertEqual(summary["failed_work_order_ids"], ["review-claims", "review-platform"])

    def test_only_contract_failure_without_valid_block_can_stage_human_review(self) -> None:
        records = [
            {
                "status": "blocked_review_failure",
                "failure": {"error_code": "craft_review_failed"},
                "initial_reviews": [],
                "post_repair_reviews": [],
            }
            for _ in range(3)
        ]
        payload = {"all_territories_advisory_pass": False, "records": records}
        self.assertTrue(_critic_failure_allows_human_review_only(payload))
        records[1] = {
            "status": "advisory_pass_pending_human_review",
            "failure": None,
            "initial_reviews": [{"review": {"decision": "pass"}}] * 3,
            "post_repair_reviews": [],
        }
        self.assertTrue(_critic_failure_allows_human_review_only(payload))
        records[0]["initial_reviews"] = [{"review": {"decision": "block"}}]
        self.assertFalse(_critic_failure_allows_human_review_only(payload))
        records[0]["initial_reviews"] = []
        records[0]["status"] = "blocked_by_advisory_review"
        self.assertFalse(_critic_failure_allows_human_review_only(payload))


if __name__ == "__main__":
    unittest.main()
