from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen-image-v2/review-packet"
CARD = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-share-card-v2/prooflaunch-performance-review-1080x1350.png"


class QwenImageNamedPKV2Tests(unittest.TestCase):
    def test_v2_packet_binds_the_new_candidate_without_votes(self) -> None:
        receipt = json.loads((PACKET_ROOT / "packet-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["category_id"], "image_generation_editing")
        self.assertEqual(receipt["reviewer_kit_count"], 5)
        self.assertEqual(receipt["submitted_review_count"], 0)
        packet = json.loads((PACKET_ROOT / "public/packet.json").read_text(encoding="utf-8"))
        candidate_sha = hashlib.sha256(CARD.read_bytes()).hexdigest()
        for task in packet["review_tasks"]:
            hashes = {task["left_asset"]["sha256"], task["right_asset"]["sha256"]}
            self.assertIn(candidate_sha, hashes)
            self.assertEqual(task["left_asset"]["media_family"], "image")
            self.assertEqual(task["right_asset"]["media_family"], "image")

    def test_public_pages_do_not_name_the_baseline_provider(self) -> None:
        for slot in range(1, 6):
            page = (PACKET_ROOT / f"public/reviewer-{slot:02d}.html").read_text(encoding="utf-8").casefold()
            self.assertNotIn("qwen", page)
            self.assertEqual(page.count("<img "), 2)


if __name__ == "__main__":
    unittest.main()
