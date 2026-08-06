from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "artifacts/comfyui-gpu-handoff-20260801/handoff.json"
DOWNLOAD_SCRIPT = ROOT / "artifacts/comfyui-gpu-handoff-20260801/download-and-verify.sh"
SUPPLY = ROOT / "evidence/v10/comfyui-weight-supply-chain.json"


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ComfyUIGPUHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))
        self.supply = json.loads(SUPPLY.read_text(encoding="utf-8"))

    def test_handoff_is_smallest_rights_legible_image_audio_closure(self) -> None:
        payload = dict(self.handoff)
        claimed = payload.pop("plan_sha256")
        self.assertEqual(claimed, canonical_sha256(payload))
        self.assertEqual(
            self.handoff["selected_workflow_ids"],
            ["qwen-image-2512", "ace-step-1.5-text-to-audio"],
        )
        self.assertEqual(self.handoff["download_count"], 8)
        self.assertEqual(self.handoff["total_size_bytes"], 46_464_106_990)
        self.assertEqual(
            self.handoff["required_free_bytes_with_20_percent_headroom"],
            55_756_928_388,
        )
        self.assertFalse(self.handoff["execution_admission_after_download"])
        license_ready = set(self.supply["model_card_license_ready_workflow_ids"])
        self.assertLessEqual(set(self.handoff["selected_workflow_ids"]), license_ready)

    def test_every_download_is_pinned_hashed_and_matches_supply_receipt(self) -> None:
        supply_downloads = {
            (item["workflow_id"], item["destination"]): item
            for item in self.supply["download_plan"]
        }
        for item in self.handoff["downloads"]:
            self.assertNotIn("/resolve/main/", item["pinned_url"])
            self.assertEqual(len(item["revision"]), 40)
            self.assertEqual(len(item["sha256"]), 64)
            self.assertEqual(
                item,
                supply_downloads[(item["workflow_id"], item["destination"])],
            )

    def test_download_script_is_explicit_resumable_and_fail_closed(self) -> None:
        content = DOWNLOAD_SCRIPT.read_text(encoding="utf-8")
        self.assertTrue(os.access(DOWNLOAD_SCRIPT, os.X_OK))
        self.assertIn("PROOFLAUNCH_CONFIRM_DOWNLOAD", content)
        self.assertIn("COMFYUI_MODELS_ROOT", content)
        self.assertIn("--continue-at -", content)
        self.assertIn("sha256sum", content)
        self.assertIn("Insufficient free space", content)
        self.assertIn('MODELS_ROOT" == "/"', content)
        self.assertNotIn("resolve/main", content)
        self.assertNotIn("token", content.lower())
        self.assertEqual(content.count("download_one https://huggingface.co/"), 8)


if __name__ == "__main__":
    unittest.main()
