from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GTMBufferAdmissionDossierV2Tests(unittest.TestCase):
    def test_dossier_is_sealed_and_reaches_ten_of_eleven_without_review_fabrication(self) -> None:
        payload = json.loads((ROOT / "evidence/v10/gtm-buffer-admission-dossier-v2.json").read_text())
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        observed = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, observed)
        self.assertEqual(payload["captured_source_count"], 7)
        self.assertGreaterEqual(payload["independent_captured_source_count"], 2)
        self.assertEqual(payload["evidence_ready_gate_count"], 10)
        self.assertEqual(payload["blocking_gate_count"], 1)
        self.assertEqual(payload["gates"]["named_human_exact_binding"], "pending_named_review")
        self.assertEqual(payload["formal_candidate_quota_credit"], 0)

    def test_all_six_costs_and_exact_windows_are_source_bound(self) -> None:
        payload = json.loads((ROOT / "evidence/v10/gtm-buffer-admission-dossier-v2.json").read_text())
        self.assertEqual(set(payload["cost_components"]), {"paid_media", "personnel", "tools", "creators", "channel_fees", "production"})
        source_hashes = {row["source_content_sha256"] for row in payload["sources"] if row["capture_status"] == "captured_and_bounded"}
        self.assertTrue(all(row["source_content_sha256"] in source_hashes for row in payload["cost_components"].values()))
        windows = [window for row in payload["sources"] for window in row.get("targeted_claim_windows", [])]
        self.assertGreaterEqual(len(windows), 15)
        for row in windows:
            self.assertEqual(row["excerpt_sha256"], hashlib.sha256(row["bounded_exact_excerpt"].encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
