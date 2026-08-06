from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/40-asset-interview-execution-room-v1"


class FortyAssetInterviewExecutionRoomV1Tests(unittest.TestCase):
    def test_b2b_routes_are_native_and_non_executing(self) -> None:
        payload = json.loads((OUTPUT / "execution-bundle.json").read_text(encoding="utf-8"))
        self.assertEqual([(row["provider"], row["role"]) for row in payload["routes"]], [("linkedin", "PRIMARY"), ("reddit", "SECONDARY")])
        self.assertEqual(payload["external_request_count"], 0)
        self.assertFalse(payload["automatic_publish_enabled"])
        self.assertFalse(payload["market_effect_observed"])
        linkedin, reddit = payload["routes"]
        self.assertEqual(linkedin["postiz_request"]["endpoint"], "/public/v1/posts")
        self.assertIsNone(reddit["postiz_request"])
        self.assertTrue(reddit["release_guard"]["builder_disclosure_first"])
        self.assertTrue(reddit["release_guard"]["moderator_fit_required"])
        self.assertEqual(len(linkedin["media_upload_manifest"]), 1)
        asset = linkedin["media_upload_manifest"][0]
        self.assertEqual(hashlib.sha256((ROOT / asset["local_path"]).read_bytes()).hexdigest(), asset["sha256"])

    def test_receipt_is_bound(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        for row in receipt["bindings"]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
