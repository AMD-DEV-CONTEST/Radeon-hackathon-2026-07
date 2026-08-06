from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/comfyui_production_backends_v1.json"
REVISION = re.compile(r"^[0-9a-f]{40}$")


class ComfyUIBackendRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_every_source_is_immutable_and_every_weight_gap_blocks_execution(self) -> None:
        backends = self.payload["backends"]
        self.assertEqual(len(backends), 7)
        self.assertEqual(len({item["backend_id"] for item in backends}), len(backends))
        for item in backends:
            self.assertRegex(item["source_revision"], REVISION)
            self.assertFalse(item["executable_admission"])
            self.assertIsNone(item["model_revision"])
            self.assertIsNone(item["commercial_use_allowed"])
            self.assertIn("target_gpu_runtime_receipt", item["blocked_by"])
        self.assertEqual(self.payload["current_executable_backend_count"], 0)

    def test_primary_lanes_use_generation_models_not_local_codec_substitutes(self) -> None:
        policy = self.payload["selection_policy"]
        self.assertEqual(policy["image_primary"], "qwen-image-2.0")
        self.assertEqual(policy["video_primary"], "wan2.2")
        self.assertEqual(policy["video_premium_legal_gated"], "ltx-2")
        self.assertEqual(policy["music_primary"], "ace-step-v1.5")
        self.assertEqual(policy["speech_primary"], "qwen3-tts")
        self.assertEqual(policy["speech_expression_editor"], "step-audio-editx")
        ids = {item["backend_id"] for item in self.payload["backends"]}
        for key in (
            "image_primary",
            "image_edit_fallback",
            "video_primary",
            "video_premium_legal_gated",
            "music_primary",
            "speech_primary",
            "speech_expression_editor",
        ):
            self.assertIn(policy[key], ids)
        serialized = json.dumps(self.payload).lower()
        self.assertNotIn("ffmpeg", serialized)
        self.assertNotIn("avfoundation", serialized)
        self.assertNotIn('"project": "stepfun-ai/step-audio"', serialized)

    def test_comfyui_stays_isolated_and_fallback_requires_human_choice(self) -> None:
        orchestration = self.payload["orchestration"]
        self.assertEqual(orchestration["integration_boundary"], "isolated_process_http_api")
        self.assertFalse(orchestration["embedded_in_core"])
        self.assertFalse(self.payload["selection_policy"]["automatic_fallback_allowed"])
        self.assertTrue(self.payload["selection_policy"]["manual_release_required"])
        self.assertTrue(self.payload["selection_policy"]["blind_review_required"])


if __name__ == "__main__":
    unittest.main()
