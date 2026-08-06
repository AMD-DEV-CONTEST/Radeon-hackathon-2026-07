from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v2/manifest.json"


class ClaimTrialShareCardV2AdmissionTests(unittest.TestCase):
    def test_revision_is_sealed_and_only_image_lane_changes(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(payload["challenger_revision"], 2)
        self.assertEqual(payload["category_count"], 13)
        self.assertEqual(payload["admitted_category_count"], 13)
        image = next(row for row in payload["categories"] if row["category_id"] == "image_generation_editing")
        self.assertIn("named-product-challenger-dossiers-v2", image["dossier"]["project_relative_path"])
        self.assertEqual(image["source_artifact_count"], 2)
        self.assertTrue(any(row["path"].endswith("prooflaunch-performance-review-1080x1350.png") for row in image["source_artifacts"]))
        self.assertFalse(payload["automatic_pairing_enabled"])
        self.assertFalse(payload["four_a_quality_proven"])


if __name__ == "__main__":
    unittest.main()
