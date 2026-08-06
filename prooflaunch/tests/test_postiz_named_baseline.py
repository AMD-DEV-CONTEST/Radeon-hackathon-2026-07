from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/postiz"
PK_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-postiz-v1"


class PostizNamedBaselineTests(unittest.TestCase):
    def test_local_run_hard_blocks_unresolved_integrations_without_external_release(self) -> None:
        raw_path = INPUT_ROOT / "postiz-raw-baseline.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        capture = json.loads((INPUT_ROOT / "capture.json").read_text(encoding="utf-8"))

        self.assertEqual(raw["schema"], "ProofLaunchPostizRawNamedBaselineV1")
        self.assertTrue(raw["runtime"]["local_only"])
        self.assertEqual(raw["runtime"]["connected_integration_count"], 0)
        self.assertEqual(raw["runtime"]["external_network_calls_during_baseline_execution"], 0)
        self.assertFalse(raw["runtime"]["api_key_persisted"])
        self.assertFalse(raw["authorization_boundary"]["automatic_publish_enabled"])
        self.assertFalse(raw["authorization_boundary"]["external_publish_attempted"])
        self.assertFalse(raw["authorization_boundary"]["external_post_created"])
        executions = raw["product_observations"]["executions"]
        self.assertEqual(len(executions), 4)
        self.assertEqual({row["actual_local_product_response"]["status"] for row in executions}, {400})
        for row in executions:
            message = row["actual_local_product_response"]["body"]["message"]
            self.assertIn("Integration with id", message)
            self.assertIn("not found", message)
            self.assertFalse(row["external_publish_attempted"])
            self.assertFalse(row["external_post_created"])
        self.assertFalse(raw["evaluation_boundary"]["successful_schedule_observed"])
        self.assertTrue(raw["evaluation_boundary"]["failure_response_observed"])
        self.assertFalse(raw["evaluation_boundary"]["market_response_observed"])
        self.assertEqual(capture["artifact"]["sha256"], hashlib.sha256(raw_path.read_bytes()).hexdigest())

    def test_public_packet_is_source_hidden_and_contains_no_fake_win(self) -> None:
        baseline_path = PK_ROOT / "private/review-asset-baseline.json"
        baseline_text = baseline_path.read_text(encoding="utf-8").casefold()
        self.assertNotIn("postiz", baseline_text)
        self.assertIn("integration with id", baseline_text)
        self.assertIn("not found", baseline_text)

        packet_root = PK_ROOT / "review-packet/public"
        packet = json.loads((packet_root / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["review_tasks"]), 5)
        page = (packet_root / "reviewer-01.html").read_text(encoding="utf-8").casefold()
        self.assertNotIn("postiz", page)
        self.assertNotIn("candidate win", page)
        self.assertEqual(page.count("<pre>"), 2)
        self.assertIn("named_human_approval_observed", page)
        receipt = json.loads((PK_ROOT / "review-packet/packet-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["submitted_review_count"], 0)
        self.assertEqual(receipt["expected_review_count"], 5)
        self.assertEqual(receipt["automatic_external_actions"], 0)


if __name__ == "__main__":
    unittest.main()
