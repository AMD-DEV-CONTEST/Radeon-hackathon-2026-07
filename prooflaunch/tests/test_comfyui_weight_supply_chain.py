from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUPPLY = ROOT / "config/comfyui_weight_supply_chain_v1.json"
MANIFEST = ROOT / "workflows/comfyui-official-20260801/manifest.json"
RECEIPT = ROOT / "evidence/v10/comfyui-weight-supply-chain.json"
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ComfyUIWeightSupplyChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.supply = json.loads(SUPPLY.read_text(encoding="utf-8"))
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_every_declared_workflow_file_has_one_immutable_hash_record(self) -> None:
        expected = {
            (workflow["workflow_id"], model["directory"], model["name"])
            for workflow in self.manifest["workflows"]
            for model in workflow["declared_models"]
        }
        observed = {
            (weight["workflow_id"], weight["directory"], weight["name"])
            for weight in self.supply["weights"]
        }
        self.assertEqual(expected, observed)
        self.assertEqual(len(observed), 18)
        for weight in self.supply["weights"]:
            self.assertRegex(weight["sha256"], SHA256)
            self.assertGreater(weight["size_bytes"], 0)

    def test_repository_revisions_and_rights_status_are_explicit(self) -> None:
        repositories = self.supply["repositories"]
        self.assertEqual(len(repositories), 8)
        for repository in repositories.values():
            self.assertRegex(repository["revision"], REVISION)
            self.assertTrue(repository["rights_status"])
            self.assertNotEqual(repository["rights_status"], "cleared")
        self.assertEqual(
            repositories["Comfy-Org/Qwen-Image_ComfyUI"]["model_card_license"],
            "apache-2.0",
        )
        self.assertEqual(
            repositories["Lightricks/LTX-2.3"]["rights_status"],
            "legal_review_required",
        )
        self.assertIn(
            "unresolved",
            repositories["Comfy-Org/ltx-2"]["rights_status"],
        )
        self.assertIn(
            "unresolved",
            repositories["Comfy-Org/Wan_2.2_ComfyUI_Repackaged"][
                "rights_status"
            ],
        )

    def test_sealed_receipt_is_self_consistent_and_fail_closed(self) -> None:
        receipt = dict(self.receipt)
        claimed = receipt.pop("receipt_sha256")
        self.assertEqual(
            claimed,
            hashlib.sha256(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        self.assertEqual(self.receipt["supply_chain_sha256"], file_sha256(SUPPLY))
        self.assertEqual(self.receipt["workflow_manifest_sha256"], file_sha256(MANIFEST))
        self.assertEqual(self.receipt["weight_count"], 18)
        self.assertEqual(self.receipt["total_size_bytes"], 131_690_015_517)
        self.assertEqual(self.receipt["installed_verified_weight_count"], 0)
        self.assertFalse(self.receipt["all_local_weights_verified"])
        self.assertFalse(self.receipt["rights_gate_passed"])
        self.assertFalse(self.receipt["target_gpu_runtime_gate_passed"])
        self.assertFalse(self.receipt["executable_admission"])
        self.assertEqual(
            self.receipt["unresolved_or_legal_review_repository_count"], 5
        )
        for entry in self.receipt["download_plan"]:
            self.assertNotIn("/resolve/main/", entry["pinned_url"])
            self.assertIn(f"/resolve/{entry['revision']}/", entry["pinned_url"])

    def test_per_workflow_storage_is_visible_before_any_download(self) -> None:
        per_workflow = self.receipt["per_workflow"]
        self.assertEqual(per_workflow["qwen-image-2512"]["weight_count"], 4)
        self.assertEqual(per_workflow["ltx-2.3-text-to-video"]["weight_count"], 4)
        self.assertEqual(per_workflow["wan2.2-text-to-video"]["weight_count"], 6)
        self.assertEqual(per_workflow["ace-step-1.5-text-to-audio"]["weight_count"], 4)
        self.assertEqual(
            self.receipt["model_card_license_ready_workflow_ids"],
            ["ace-step-1.5-text-to-audio", "qwen-image-2512"],
        )
        self.assertTrue(
            per_workflow["qwen-image-2512"]["model_card_license_gate_passed"]
        )
        self.assertTrue(
            per_workflow["ace-step-1.5-text-to-audio"][
                "model_card_license_gate_passed"
            ]
        )
        self.assertFalse(
            per_workflow["wan2.2-text-to-video"]["model_card_license_gate_passed"]
        )
        self.assertFalse(
            per_workflow["ltx-2.3-text-to-video"][
                "model_card_license_gate_passed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
