from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "evidence/v10/gtm-flodesk-admission-dossier-v2.json"


class GTMFlodeskAdmissionDossierV2Tests(unittest.TestCase):
    def test_dossier_is_multi_source_bounded_and_fail_closed(self) -> None:
        payload = json.loads(PATH.read_text())
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        digest = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, digest)
        self.assertEqual(payload["source_count"], 7)
        self.assertEqual(payload["captured_source_count"], 7)
        self.assertGreaterEqual(payload["independent_captured_source_count"], 2)
        self.assertEqual(payload["evidence_ready_gate_count"], 10)
        self.assertEqual(payload["blocking_gate_count"], 1)
        self.assertEqual(payload["formal_candidate_quota_credit"], 0)
        self.assertFalse(payload["automatic_promotion_allowed"])
        self.assertTrue(payload["gates"]["six_cost_components"].startswith("evidence_ready"))
        self.assertTrue(payload["gates"]["independent_outcome_surface"].startswith("evidence_ready"))
        self.assertEqual(payload["gates"]["named_human_exact_binding"], "pending_named_review")
        self.assertEqual(set(payload["cost_components"]), {"paid_media", "personnel", "tools", "creators", "channel_fees", "production"})
        self.assertTrue(all(row["amount_usd"] is None for row in payload["cost_components"].values()))
        self.assertTrue(all(row.get("raw_page_retained") is False for row in payload["sources"] if row["capture_status"] == "captured_and_bounded"))


if __name__ == "__main__":
    unittest.main()
