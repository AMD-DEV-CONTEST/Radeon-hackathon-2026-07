from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GTMParqetAdmissionDossierV2Tests(unittest.TestCase):
    def test_parqet_is_a_strict_ten_of_eleven_dossier(self) -> None:
        payload = json.loads((ROOT / "evidence/v10/gtm-parqet-admission-dossier-v2.json").read_text())
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        observed = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, observed)
        self.assertEqual(payload["captured_source_count"], 7)
        self.assertGreaterEqual(payload["independent_captured_source_count"], 2)
        self.assertEqual(payload["evidence_ready_gate_count"], 10)
        self.assertEqual(payload["blocking_gate_count"], 1)
        self.assertTrue(payload["early_zero_paid_statement_present"])
        self.assertEqual(payload["cost_components"]["tools"]["amount_usd"], 500)
        self.assertIsNone(payload["cost_components"]["paid_media"]["amount_usd"])
        self.assertEqual(payload["gates"]["named_human_exact_binding"], "pending_named_review")

    def test_named_review_page_preserves_zero_credit(self) -> None:
        manifest = json.loads((ROOT / "artifacts/gtm-parqet-named-review-v2/manifest.json").read_text())
        self.assertEqual(manifest["company"], "Parqet")
        self.assertEqual(manifest["formal_candidate_quota_credit"], 0)
        self.assertFalse(manifest["automatic_promotion_allowed"])


if __name__ == "__main__":
    unittest.main()
