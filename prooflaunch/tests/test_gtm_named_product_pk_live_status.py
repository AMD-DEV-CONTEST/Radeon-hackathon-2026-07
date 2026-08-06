from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "evidence/v10/gtm-named-product-pk-live-status-v1.json"


class GTMNamedProductPKLiveStatusTests(unittest.TestCase):
    def test_live_baselines_and_packets_are_real_but_not_wins(self) -> None:
        payload = json.loads(STATUS.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(supplied, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(payload["row_count"], 130)
        self.assertEqual(payload["authorized_baseline_count"], 7)
        self.assertEqual(payload["blind_review_packet_count"], 7)
        self.assertEqual(payload["submitted_human_review_count"], 0)
        self.assertEqual(payload["completed_product_pk_rows"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        qwen = next(row for row in payload["rows"] if row["reference_product"] == "Qwen3-TTS")
        self.assertTrue(qwen["authorized_baseline_present"])
        self.assertTrue(qwen["blind_review_packet_ready"])
        self.assertEqual(qwen["status"], "blind_review_packet_ready_awaiting_five_humans")
        qwen_image = next(row for row in payload["rows"] if row["reference_product"] == "Qwen-Image")
        self.assertTrue(qwen_image["authorized_baseline_present"])
        self.assertTrue(qwen_image["blind_review_packet_ready"])
        self.assertEqual(qwen_image["status"], "blind_review_packet_ready_awaiting_five_humans")
        self.assertIn("named-product-pk-qwen-image-v2", qwen_image["active_packet_receipt_path"])
        self.assertRegex(qwen_image["active_packet_receipt_sha256"], r"^[0-9a-f]{64}$")
        openai_image = next(row for row in payload["rows"] if row["reference_product"] == "OpenAI Image")
        self.assertTrue(openai_image["authorized_baseline_present"])
        self.assertTrue(openai_image["blind_review_packet_ready"])
        self.assertEqual(openai_image["status"], "blind_review_packet_ready_awaiting_five_humans")
        self.assertIn("named-product-pk-openai-image-v1", openai_image["active_packet_receipt_path"])
        mem0 = next(row for row in payload["rows"] if row["reference_product"] == "Mem0")
        self.assertTrue(mem0["authorized_baseline_present"])
        self.assertTrue(mem0["blind_review_packet_ready"])
        self.assertEqual(mem0["status"], "blind_review_packet_ready_awaiting_five_humans")
        letta = next(row for row in payload["rows"] if row["reference_product"] == "Letta")
        self.assertTrue(letta["authorized_baseline_present"])
        self.assertTrue(letta["blind_review_packet_ready"])
        self.assertEqual(letta["status"], "blind_review_packet_ready_awaiting_five_humans")
        memos = next(row for row in payload["rows"] if row["reference_product"] == "MemOS")
        self.assertTrue(memos["authorized_baseline_present"])
        self.assertTrue(memos["blind_review_packet_ready"])
        self.assertEqual(memos["status"], "blind_review_packet_ready_awaiting_five_humans")
        postiz = next(row for row in payload["rows"] if row["reference_product"] == "Postiz")
        self.assertTrue(postiz["authorized_baseline_present"])
        self.assertTrue(postiz["blind_review_packet_ready"])
        self.assertEqual(postiz["status"], "blind_review_packet_ready_awaiting_five_humans")

    def test_public_memos_memory_review_is_source_hidden_and_truth_bounded(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-memos-v2/review-packet/public"
        packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["review_tasks"]), 5)
        page = (root / "reviewer-01.html").read_text(encoding="utf-8").lower()
        for provider_name in ("memos", "memtensor", "qwen", "ollama", "qdrant", "bge"):
            self.assertNotIn(provider_name, page)
        self.assertEqual(page.count("<pre>"), 2)
        self.assertIn("automatic_conflict_history_observed", page)
        self.assertIn("false", page)

    def test_public_audio_review_is_source_hidden_and_playable_by_contract(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen3-tts-v1/review-packet/public"
        packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["review_tasks"]), 5)
        for task in packet["review_tasks"]:
            self.assertEqual(task["left_asset"]["media_family"], "audio")
            self.assertEqual(task["right_asset"]["media_family"], "audio")
            self.assertNotEqual(task["left_asset"]["sha256"], task["right_asset"]["sha256"])
        page = (root / "reviewer-01.html").read_text(encoding="utf-8").lower()
        self.assertNotIn("qwen", page)
        self.assertEqual(page.count("<audio "), 2)

    def test_public_image_review_is_source_hidden_and_image_to_image(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen-image-v2/review-packet/public"
        packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["review_tasks"]), 5)
        for task in packet["review_tasks"]:
            self.assertEqual(task["left_asset"]["media_family"], "image")
            self.assertEqual(task["right_asset"]["media_family"], "image")
            self.assertNotEqual(task["left_asset"]["sha256"], task["right_asset"]["sha256"])
        page = (root / "reviewer-01.html").read_text(encoding="utf-8").lower()
        self.assertNotIn("qwen", page)
        self.assertEqual(page.count("<img "), 2)

    def test_public_openai_image_review_is_source_hidden_and_image_to_image(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-openai-image-v1/review-packet/public"
        packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["review_tasks"]), 5)
        for task in packet["review_tasks"]:
            self.assertEqual(task["left_asset"]["media_family"], "image")
            self.assertEqual(task["right_asset"]["media_family"], "image")
            self.assertNotEqual(task["left_asset"]["sha256"], task["right_asset"]["sha256"])
        page = (root / "reviewer-01.html").read_text(encoding="utf-8").lower()
        self.assertNotIn("openai", page)
        self.assertEqual(page.count("<img "), 2)

    def test_public_memory_review_is_source_hidden_and_offline_readable(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/review-packet/public"
        packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["review_tasks"]), 5)
        for task in packet["review_tasks"]:
            self.assertEqual(task["left_asset"]["media_family"], "document")
            self.assertEqual(task["right_asset"]["media_family"], "document")
        page = (root / "reviewer-01.html").read_text(encoding="utf-8").lower()
        for provider_name in ("mem0", "qwen", "ollama", "qdrant", "bge"):
            self.assertNotIn(provider_name, page)
        self.assertEqual(page.count("<pre>"), 2)
        self.assertNotIn("data-text-path", page)
        self.assertIn("desktop_search_after_update", page)
        self.assertIn("cross_device_retrieval_succeeded", page)

    def test_public_letta_memory_review_is_source_hidden_and_exposes_model_failure(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-letta-v1/review-packet/public"
        packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["review_tasks"]), 5)
        page = (root / "reviewer-01.html").read_text(encoding="utf-8").lower()
        for provider_name in ("letta", "memgpt", "qwen", "ollama", "bge"):
            self.assertNotIn(provider_name, page)
        self.assertEqual(page.count("<pre>"), 2)
        self.assertIn("model_answer_retrieved_newer_channel", page)
        self.assertIn("desktop_answer_after_mobile_update", page)


if __name__ == "__main__":
    unittest.main()
