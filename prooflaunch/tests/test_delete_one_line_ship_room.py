from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-ship-room-v1"


class DeleteOneLineShipRoomTests(unittest.TestCase):
    def test_ship_room_exposes_real_work_and_zero_effect_state(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(receipt["finished_slide_count"], 5)
        self.assertEqual(receipt["held_channel_decision_count"], 7)
        self.assertEqual(receipt["authorized_same_task_baseline_count"], 3)
        self.assertEqual(receipt["source_hidden_packet_count"], 3)
        self.assertEqual(receipt["submitted_human_review_count"], 0)
        self.assertEqual(receipt["candidate_win_count"], 0)
        self.assertEqual(receipt["external_action_count"], 0)
        self.assertFalse(receipt["production_effect_observed"])
        page = (OUTPUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("0 SHIPPED", page)
        self.assertIn("3 REAL FIGHTS", page)
        self.assertIn("Qwen-Image", page)
        self.assertIn("Qwen3‑TTS", page)
        self.assertIn("Mem0", page)
        self.assertEqual(page.count('class="review"'), 5)
        self.assertEqual(page.count('class="review audio"'), 5)
        self.assertEqual(page.count('class="review memory"'), 5)
        self.assertEqual(page.count('class="queue-card"'), 7)
        self.assertNotIn("candidate won", page.lower())


if __name__ == "__main__":
    unittest.main()
