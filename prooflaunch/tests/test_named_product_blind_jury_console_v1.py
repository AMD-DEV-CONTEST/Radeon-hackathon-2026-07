from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-blind-jury-console-v1"


class NamedProductBlindJuryConsoleV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        self.status = json.loads((OUTPUT / "status.json").read_text(encoding="utf-8"))

    def test_console_is_sealed_and_starts_from_real_review_state(self) -> None:
        for payload in (self.receipt, self.status):
            unsigned = dict(payload)
            supplied = unsigned.pop("content_sha256")
            canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(self.receipt["lane_count"], 7)
        self.assertEqual(self.receipt["reviewer_link_count"], 35)
        self.assertEqual(self.receipt["expected_review_count"], 35)
        self.assertEqual(self.receipt["submitted_review_count"], 0)
        self.assertEqual(self.receipt["completed_comparison_count"], 0)
        self.assertEqual(self.receipt["candidate_win_count"], 0)
        self.assertFalse(self.receipt["private_mapping_exposed"])
        self.assertFalse(self.receipt["model_judge_can_promote"])

    def test_console_binds_seven_real_packets_and_all_reviewer_pages(self) -> None:
        self.assertEqual(len(self.receipt["packet_bindings"]), 7)
        for binding in self.receipt["packet_bindings"]:
            path = ROOT / binding["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), binding["sha256"])
        html = (OUTPUT / "index.html").read_text(encoding="utf-8")
        for lane in ("qwen-image-v2", "openai-image-v1", "qwen3-tts-v1", "mem0-v2", "letta-v1", "memos-v2", "postiz-v1"):
            for slot in range(1, 6):
                self.assertIn(f"named-product-pk-{lane}/review-packet/public/reviewer-{slot:02d}.html", html)
        self.assertNotIn("task_side_mapping", html)
        self.assertNotIn("private/mapping.json", html)

    def test_import_commands_are_lane_bound(self) -> None:
        commands = {row["id"]: row["import_command"] for row in self.status["lanes"]}
        self.assertEqual(set(commands), {"image", "image_openai", "audio", "memory", "memory_letta", "memory_memos", "scheduling_postiz"})
        for lane, command in commands.items():
            self.assertIn(f"--lane {lane}", command)
            self.assertIn(f"inbox/{lane}/REVIEW.json", command)


if __name__ == "__main__":
    unittest.main()
