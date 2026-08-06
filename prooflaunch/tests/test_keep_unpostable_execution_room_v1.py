from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-execution-room-v1"


class KeepUnpostableExecutionRoomV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads((OUTPUT / "execution-bundle.json").read_text(encoding="utf-8"))

    def test_two_route_execution_bundle_is_platform_native_and_non_executing(self) -> None:
        self.assertEqual(self.payload["activation_policy"], "one_primary_tiktok_plus_one_secondary_instagram")
        self.assertEqual([row["provider"] for row in self.payload["routes"]], ["tiktok", "instagram"])
        self.assertEqual([row["role"] for row in self.payload["routes"]], ["PRIMARY", "SECONDARY"])
        self.assertEqual(self.payload["external_request_count"], 0)
        self.assertFalse(self.payload["automatic_publish_enabled"])
        self.assertFalse(self.payload["market_effect_observed"])
        self.assertEqual(len(self.payload["execution_graph"]), 7)
        self.assertEqual(self.payload["learning_decision_compiler"], "scripts/compile_keep_unpostable_learning_decision_v1.py")
        for row in self.payload["routes"]:
            self.assertIn("Synthetic concept. No app, user result or market effect exists.", row["caption"])
            self.assertTrue(row["first_comment"])
            self.assertGreaterEqual(len(row["conversation_tree"]), 2)
            self.assertIsNone(row["tracking"]["outbound_url"])
            self.assertEqual(row["postiz_request"]["endpoint"], "/public/v1/posts")
            self.assertFalse(row["release_guard"]["automatic_publish_enabled"])
            self.assertFalse(row["release_guard"]["external_request_executed"])

    def test_media_is_real_and_hash_bound(self) -> None:
        media = [item for row in self.payload["routes"] for item in row["media_upload_manifest"]]
        self.assertEqual(len(media), 6)
        for item in media:
            path = ROOT / item["local_path"]
            self.assertTrue(path.is_file(), item["local_path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
            self.assertEqual(path.stat().st_size, item["bytes"])

    def test_tiktok_and_instagram_requests_preserve_native_settings(self) -> None:
        by_provider = {row["provider"]: row for row in self.payload["routes"]}
        tiktok = by_provider["tiktok"]["postiz_request"]["payload"]["posts"][0]["settings"]
        instagram = by_provider["instagram"]["postiz_request"]["payload"]["posts"][0]["settings"]
        self.assertEqual(tiktok["privacy_level"], "SELF_ONLY")
        self.assertTrue(tiktok["video_made_with_ai"])
        self.assertEqual(tiktok["content_posting_method"], "UPLOAD")
        self.assertEqual(instagram["post_type"], "post")
        self.assertEqual(len(by_provider["instagram"]["media_upload_manifest"]), 5)

    def test_observation_template_is_empty_and_privacy_safe(self) -> None:
        observation = json.loads((OUTPUT / "observation-template.json").read_text(encoding="utf-8"))
        self.assertEqual(observation["status"], "EMPTY_AWAITING_AUTHORIZED_RELEASE")
        self.assertEqual(len(observation["rows"]), 2)
        self.assertIn("never record the private moment", observation["privacy"])
        for row in observation["rows"]:
            self.assertIsNone(row["release_url"])
            self.assertIsNone(row["owner_decision"])
            self.assertEqual(row["evidence_urls"], [])

    def test_page_exposes_execution_and_learning_handoffs(self) -> None:
        html = (OUTPUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("OPEN HUMAN RELEASE JURY", html)
        self.assertIn("DOWNLOAD EXECUTION JSON", html)
        self.assertIn("DOWNLOAD 7-DAY OBSERVATION TEMPLATE", html)
        self.assertIn("INSPECT CURRENT LEARNING DECISION", html)

    def test_receipt_is_sealed_and_bindings_match(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(), supplied)
        for row in receipt["bindings"]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
