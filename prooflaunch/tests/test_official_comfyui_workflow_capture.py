from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workflows/comfyui-official-20260801/manifest.json"


class OfficialComfyUIWorkflowCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_and_all_official_blueprints_are_content_addressed(self) -> None:
        basis = dict(self.payload)
        claimed = basis.pop("manifest_sha256")
        self.assertEqual(
            claimed,
            hashlib.sha256(
                json.dumps(basis, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        self.assertEqual(self.payload["workflow_count"], 4)
        for workflow in self.payload["workflows"]:
            path = ROOT / workflow["local_path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), workflow["sha256"])
            self.assertTrue(workflow["inputs"])
            self.assertTrue(workflow["outputs"])
            self.assertTrue(workflow["declared_models"])

    def test_official_api_exports_are_sealed_but_execution_remains_blocked(self) -> None:
        self.assertEqual(self.payload["api_format_export_count"], 4)
        self.assertEqual(self.payload["executable_workflow_count"], 0)
        for workflow in self.payload["workflows"]:
            self.assertEqual(
                workflow["source_format"], "comfyui_native_subgraph_blueprint"
            )
            self.assertTrue(workflow["api_format_exported"])
            self.assertFalse(workflow["executable_admission"])
            self.assertEqual(
                workflow["api_export_method"],
                "official_frontend_app.loadGraphData_then_app.graphToPrompt",
            )
            self.assertEqual(workflow["api_export_frontend_version"], "1.47.11")
            self.assertEqual(
                workflow["api_export_core_revision"],
                "2881e6161081439b1c3fb3b6c1f51b3d272da710",
            )
            api_path = ROOT / workflow["api_local_path"]
            receipt_path = ROOT / workflow["api_export_receipt_path"]
            self.assertEqual(
                hashlib.sha256(api_path.read_bytes()).hexdigest(),
                workflow["api_sha256"],
            )
            api_workflow = json.loads(api_path.read_text(encoding="utf-8"))
            self.assertEqual(len(api_workflow), workflow["api_output_node_count"])
            self.assertTrue(
                all(
                    isinstance(node.get("inputs"), dict)
                    and isinstance(node.get("class_type"), str)
                    for node in api_workflow.values()
                )
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertFalse(receipt["inference_executed"])
            self.assertFalse(receipt["models_loaded"])
            self.assertFalse(receipt["gpu_used"])
            self.assertEqual(receipt["missing_node_count"], 0)
            self.assertEqual(
                set(workflow["blocked_by"]),
                {
                    "immutable_model_weight_revisions",
                    "weight_sha256_receipts",
                    "model_license_and_commercial_rights_receipts",
                    "target_gpu_runtime_receipt",
                },
            )
            for model in workflow["declared_models"]:
                self.assertIn("/resolve/main/", model["url"])

    def test_capture_covers_image_video_and_audio_primary_lanes(self) -> None:
        outputs = {
            item["workflow_id"]: {output["type"] for output in item["outputs"]}
            for item in self.payload["workflows"]
        }
        self.assertEqual(outputs["qwen-image-2512"], {"IMAGE"})
        self.assertEqual(outputs["ltx-2.3-text-to-video"], {"VIDEO"})
        self.assertEqual(outputs["wan2.2-text-to-video"], {"VIDEO"})
        self.assertEqual(outputs["ace-step-1.5-text-to-audio"], {"AUDIO"})


if __name__ == "__main__":
    unittest.main()
