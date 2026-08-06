from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_named_product_baseline import (
    CAPTURE_SCHEMA,
    NamedProductBaselineError,
    content_sha256,
    import_capture,
    validate_kit_manifest,
)
from scripts.export_gtm_named_product_baseline_capture_kit import export


ROOT = Path(__file__).resolve().parents[1]


class GTMNamedProductBaselineTests(unittest.TestCase):
    def _kit(self, temporary: str) -> tuple[Path, dict]:
        output = Path(temporary) / "kit"
        export(output)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        return output, manifest

    def _capture(self, slot: dict, artifact: Path, **overrides: object) -> dict:
        payload = {
            "schema": CAPTURE_SCHEMA,
            "capture_slot_id": slot["capture_slot_id"],
            "category_id": slot["category_id"],
            "reference_product": slot["reference_product"],
            "reference_product_url": slot["reference_product_url"],
            "frozen_brief_sha256": slot["frozen_brief_sha256"],
            "operator_id": "qualified-operator-01",
            "captured_at": "2026-08-03T06:00:00Z",
            "provider_model_or_version": "observed-product-build",
            "acquisition_method": "authorized_product_use",
            "rights_attestation": {
                "authorized_to_evaluate_and_retain": True,
                "same_frozen_brief_without_hidden_editing": True,
                "provider_and_version_recorded_truthfully": True,
            },
            "artifact": {
                "name": artifact.name,
                "mime_type": "application/json",
                "bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            },
        }
        payload.update(overrides)
        payload["content_sha256"] = content_sha256(payload)
        return payload

    def test_exports_13_briefs_and_130_rights_bound_slots(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, manifest = self._kit(temporary)
            validate_kit_manifest(manifest, kit_root=output)
            self.assertEqual(manifest["category_count"], 13)
            self.assertEqual(manifest["capture_slot_count"], 130)
            self.assertEqual(len(manifest["frozen_briefs"]), 13)
            self.assertEqual(len({slot["capture_slot_id"] for slot in manifest["capture_slots"]}), 130)
            self.assertFalse(manifest["network_submission_enabled"])
            self.assertFalse(manifest["automatic_product_execution_enabled"])
            self.assertFalse(manifest["automatic_pk_promotion_enabled"])
            self.assertTrue(manifest["human_review_required"])
            for index in range(1, 14):
                page = (output / f"category-{index:02d}.html").read_text(encoding="utf-8")
                self.assertIn("I am authorized to evaluate and retain this output", page)
                self.assertIn("A capture is not a win", page)

    def test_import_binds_exact_artifact_but_never_promotes_pk(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, manifest = self._kit(temporary)
            slot = next(item for item in manifest["capture_slots"] if item["category_id"] == "cross_device_memory")
            artifact = Path(temporary) / "provider-original-export.json"
            artifact.write_text('{"answer":"authorized same-brief output"}\n', encoding="utf-8")
            capture = self._capture(slot, artifact)
            receipt = Path(temporary) / "capture.json"
            receipt.write_text(json.dumps(capture), encoding="utf-8")
            registry = import_capture(
                manifest_path=output / "manifest.json",
                capture_path=receipt,
                artifact_path=artifact,
                store_root=Path(temporary) / "store",
            )
            self.assertEqual(registry["authorized_baseline_count"], 1)
            self.assertEqual(registry["remaining_baseline_count"], 129)
            self.assertEqual(registry["completed_product_pk_rows"], 0)
            self.assertEqual(registry["submitted_human_review_count"], 0)
            self.assertEqual(registry["effect_aligned_category_count"], 0)
            self.assertFalse(registry["automatic_pairing_enabled"])
            self.assertFalse(registry["automatic_pk_promotion_enabled"])
            stored = Path(temporary) / "store" / slot["capture_slot_id"] / artifact.name
            self.assertTrue(stored.is_file())
            self.assertEqual(stored.read_bytes(), artifact.read_bytes())

    def test_import_fails_on_hash_drift_or_missing_rights(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, manifest = self._kit(temporary)
            slot = manifest["capture_slots"][0]
            artifact = Path(temporary) / "baseline.json"
            artifact.write_text('{"answer":"one"}\n', encoding="utf-8")
            capture = self._capture(slot, artifact)
            capture["rights_attestation"]["authorized_to_evaluate_and_retain"] = False
            capture["content_sha256"] = content_sha256(capture)
            receipt = Path(temporary) / "capture.json"
            receipt.write_text(json.dumps(capture), encoding="utf-8")
            with self.assertRaisesRegex(NamedProductBaselineError, "attestations"):
                import_capture(manifest_path=output / "manifest.json", capture_path=receipt, artifact_path=artifact, store_root=Path(temporary) / "store")
            valid = self._capture(slot, artifact)
            receipt.write_text(json.dumps(valid), encoding="utf-8")
            artifact.write_text('{"answer":"tampered"}\n', encoding="utf-8")
            with self.assertRaisesRegex(NamedProductBaselineError, "bytes do not match"):
                import_capture(manifest_path=output / "manifest.json", capture_path=receipt, artifact_path=artifact, store_root=Path(temporary) / "store")

    def test_import_is_idempotent_and_slot_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, manifest = self._kit(temporary)
            slot = manifest["capture_slots"][0]
            artifact = Path(temporary) / "baseline.json"
            artifact.write_text('{"answer":"one"}\n', encoding="utf-8")
            capture = self._capture(slot, artifact)
            receipt = Path(temporary) / "capture.json"
            receipt.write_text(json.dumps(capture), encoding="utf-8")
            store = Path(temporary) / "store"
            first = import_capture(manifest_path=output / "manifest.json", capture_path=receipt, artifact_path=artifact, store_root=store)
            second = import_capture(manifest_path=output / "manifest.json", capture_path=receipt, artifact_path=artifact, store_root=store)
            self.assertEqual(first, second)
            changed = self._capture(slot, artifact, provider_model_or_version="different")
            receipt.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(NamedProductBaselineError, "immutable"):
                import_capture(manifest_path=output / "manifest.json", capture_path=receipt, artifact_path=artifact, store_root=store)


if __name__ == "__main__":
    unittest.main()
