from pathlib import Path
import json
import unittest

from scripts.adversarial_holdout_check import run


ROOT = Path(__file__).parent.parent / "evaluation" / "fuzzy_holdout_v1"
EXPECTED_MANIFEST_SHA256 = "ac65870e5ad9a59ea9ae0c743761d828adeaaa437e945b408a051337c5a0107f"


class FuzzyHoldoutGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run(ROOT)

    def test_holdout_is_frozen_and_large_enough(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(EXPECTED_MANIFEST_SHA256, manifest["query_manifest_sha256"])
        self.assertGreaterEqual(manifest["cases"], 300)
        self.assertTrue(manifest["synthetic_only"])

    def test_championship_quality_thresholds(self):
        metrics = self.result["metrics"]
        self.assertGreaterEqual(metrics["intent_contract_accuracy"], 0.95)
        self.assertGreaterEqual(metrics["single_target_top1_accuracy"], 0.95)
        self.assertGreaterEqual(metrics["multi_target_full_coverage_accuracy"], 0.95)
        self.assertGreaterEqual(metrics["no_match_accuracy"], 0.95)
        self.assertGreaterEqual(metrics["clarification_accuracy"], 0.95)
        self.assertEqual(0, metrics["unsafe_wrong_auto_selections"])
