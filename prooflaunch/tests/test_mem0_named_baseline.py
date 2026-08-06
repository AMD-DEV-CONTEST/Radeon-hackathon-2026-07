from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/mem0"
PRIVATE_REVIEW_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/private"


class Mem0NamedBaselineTests(unittest.TestCase):
    def test_admitted_run_proves_only_the_declared_memory_mechanics(self) -> None:
        raw_path = BASELINE_ROOT / "mem0-raw-baseline.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        provenance = json.loads((BASELINE_ROOT / "provenance.json").read_text(encoding="utf-8"))
        capture = json.loads((BASELINE_ROOT / "capture.json").read_text(encoding="utf-8"))

        self.assertEqual(raw["schema"], "ProofLaunchMem0NamedProductRawRunV1")
        self.assertTrue(raw["raw_product_output_unedited"])
        self.assertEqual(raw["external_network_calls"], 0)
        self.assertTrue(all(operation["ok"] for operation in raw["operations"]))
        operation_names = [operation["operation"] for operation in raw["operations"]]
        self.assertIn("desktop_search_after_update", operation_names)
        self.assertIn("tenant_b_isolation_search", operation_names)
        self.assertIn("tenant_a_get_all_after_delete", operation_names)
        history = next(operation for operation in raw["operations"] if operation["operation"].startswith("history_"))
        self.assertEqual([event["event"] for event in history["result"]], ["ADD", "UPDATE"])

        evaluation = provenance["evaluation"]
        self.assertTrue(evaluation["all_operations_succeeded"])
        self.assertTrue(evaluation["newer_channel_retrieved"])
        self.assertFalse(evaluation["stale_channel_asserted_as_current"])
        self.assertTrue(evaluation["source_provenance_present"])
        self.assertTrue(evaluation["tenant_isolation_observed"])
        self.assertTrue(evaluation["exact_deletion_observed"])
        self.assertIn("not a claim", provenance["truth_boundary"].lower())

        digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        self.assertEqual(capture["artifact"]["sha256"], digest)
        self.assertEqual(provenance["artifact"]["sha256"], digest)

    def test_source_hidden_transform_removes_identity_only(self) -> None:
        review_path = PRIVATE_REVIEW_ROOT / "review-asset-baseline.json"
        receipt_path = PRIVATE_REVIEW_ROOT / "anonymization-receipt.json"
        review_text = review_path.read_text(encoding="utf-8")
        review = json.loads(review_text)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        self.assertEqual(review["schema"], "ProofLaunchSourceHiddenMemoryExecutionRunV1")
        self.assertNotIn("mem0", review_text.casefold())
        self.assertEqual(receipt["semantic_fields_removed"], [])
        self.assertTrue(receipt["content_preserved_except_provider_identity"])
        self.assertFalse(receipt["automatic_promotion_enabled"])
        self.assertEqual(receipt["review_sha256"], hashlib.sha256(review_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
