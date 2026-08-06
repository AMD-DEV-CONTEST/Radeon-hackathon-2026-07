from __future__ import annotations

import hashlib
import json
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen3-tts-v1/review-packet"
PORTFOLIO = ROOT / "evidence/v10/delete-one-line-five-lane-named-pk-portfolio-v3.json"


def verify(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    supplied = payload.pop("content_sha256")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if supplied != hashlib.sha256(canonical).hexdigest():
        raise AssertionError(f"sealed payload drifted: {path}")
    payload["content_sha256"] = supplied
    return payload


class DeleteOneLineAudioPKTests(unittest.TestCase):
    def test_existing_qwen3_packet_is_real_source_hidden_same_script_work(self) -> None:
        public = verify(PACKET / "public/packet.json")
        private = verify(PACKET / "private/mapping.json")
        self.assertEqual(public["expected_review_count"], 5)
        self.assertEqual(public["submitted_review_count"], 0)
        self.assertFalse(public["source_roles_exposed"])
        self.assertFalse(public["model_judge_can_promote"])
        self.assertEqual(len(private["task_side_mapping"]), 5)
        hashes = {asset["sha256"] for task in public["review_tasks"] for asset in (task["left_asset"], task["right_asset"])}
        self.assertEqual(hashes, {private["baseline_review_sha256"], private["candidate_review_sha256"]})
        for metadata in public["files"].values():
            self.assertGreater(metadata["bytes"], 0)
        for path in (PACKET / "public/assets").glob("*.wav"):
            with wave.open(str(path), "rb") as audio:
                self.assertGreater(audio.getnframes(), 0)
                self.assertIn(audio.getframerate(), (24000, 48000))

    def test_five_lane_portfolio_adds_only_one_real_audio_baseline(self) -> None:
        payload = verify(PORTFOLIO)
        self.assertEqual(payload["lane_count"], 5)
        self.assertEqual(payload["named_product_row_count"], 50)
        self.assertEqual(payload["authorized_named_product_baseline_count"], 2)
        self.assertEqual(payload["source_hidden_five_human_packet_count"], 2)
        self.assertEqual(payload["qualified_human_review_count"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        qwen = next(row for row in payload["rows"] if row["reference_product"] == "Qwen3-TTS")
        self.assertTrue(qwen["authorized_named_product_baseline_present"])
        self.assertTrue(qwen["source_hidden_five_human_packet_present"])
        self.assertFalse(qwen["candidate_won"])


if __name__ == "__main__":
    unittest.main()
