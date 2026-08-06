from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER_MANIFEST = ROOT / "workflows/comfyui-execution-wrappers-20260801/manifest.json"
SCHEMA_RECEIPT = ROOT / "evidence/v10/comfyui-execution-wrapper-schema.json"
PROMPT_RECEIPT = ROOT / "evidence/v10/comfyui-wrapper-prompt-validation.json"


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ComfyUIExecutionWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(WRAPPER_MANIFEST.read_text(encoding="utf-8"))
        self.schema_receipt = json.loads(SCHEMA_RECEIPT.read_text(encoding="utf-8"))
        self.prompt_receipt = json.loads(PROMPT_RECEIPT.read_text(encoding="utf-8"))

    def test_each_wrapper_adds_exactly_one_official_output_node(self) -> None:
        self.assertEqual(self.manifest["wrapper_count"], 4)
        self.assertEqual(self.manifest["executable_wrapper_count"], 0)
        for record in self.manifest["records"]:
            official_path = ROOT / record["official_api_path"]
            wrapper_path = ROOT / record["wrapper_path"]
            self.assertEqual(
                hashlib.sha256(official_path.read_bytes()).hexdigest(),
                record["official_api_sha256"],
            )
            self.assertEqual(
                hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
                record["wrapper_sha256"],
            )
            official = json.loads(official_path.read_text(encoding="utf-8"))
            wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
            self.assertEqual(set(wrapper) - set(official), {record["output_node_id"]})
            self.assertEqual(record["wrapper_node_count"], len(official) + 1)
            output_node = wrapper[record["output_node_id"]]
            self.assertEqual(
                output_node["class_type"], record["output_node_class_type"]
            )
            self.assertIn(
                record["output_node_class_type"],
                {"SaveImage", "SaveAudioAdvanced", "SaveVideo"},
            )
            links = [
                value
                for value in output_node["inputs"].values()
                if isinstance(value, list) and len(value) == 2
            ]
            self.assertIn([record["terminal_media_node_id"], 0], links)
            self.assertFalse(record["inference_executed"])
            self.assertFalse(record["executable_admission"])

    def test_manifest_and_runtime_schema_receipt_are_self_authenticating(self) -> None:
        manifest = dict(self.manifest)
        claimed_manifest = manifest.pop("manifest_sha256")
        self.assertEqual(claimed_manifest, canonical_sha256(manifest))
        receipt = dict(self.schema_receipt)
        claimed_receipt = receipt.pop("receipt_sha256")
        self.assertEqual(claimed_receipt, canonical_sha256(receipt))
        self.assertEqual(self.schema_receipt["validated_wrapper_count"], 4)
        self.assertFalse(self.schema_receipt["prompt_submitted"])
        self.assertFalse(self.schema_receipt["inference_executed"])
        self.assertFalse(self.schema_receipt["target_gpu_used"])
        self.assertFalse(self.schema_receipt["executable_admission"])
        for record in self.schema_receipt["validation_records"]:
            self.assertTrue(record["output_node"])
            self.assertTrue(record["required_inputs"])

    def test_real_prompt_validator_accepts_structure_and_only_reports_missing_models(self) -> None:
        receipt = dict(self.prompt_receipt)
        claimed = receipt.pop("receipt_sha256")
        self.assertEqual(claimed, canonical_sha256(receipt))
        self.assertEqual(self.prompt_receipt["validated_wrapper_count"], 4)
        self.assertEqual(self.prompt_receipt["prompt_queued_count"], 0)
        self.assertFalse(self.prompt_receipt["inference_executed"])
        self.assertFalse(self.prompt_receipt["gpu_used"])
        self.assertFalse(self.prompt_receipt["executable_admission"])
        self.assertEqual(
            self.prompt_receipt["validation_result"],
            "structure_accepted_blocked_only_by_missing_model_inventory",
        )
        for record in self.prompt_receipt["records"]:
            self.assertEqual(record["http_status"], 400)
            self.assertFalse(record["prompt_queued"])
            self.assertFalse(record["output_wrapper_validation_error"])
            self.assertTrue(record["only_missing_model_inventory_errors_observed"])
            self.assertEqual(record["validation_error_types"], ["value_not_in_list"])


if __name__ == "__main__":
    unittest.main()
