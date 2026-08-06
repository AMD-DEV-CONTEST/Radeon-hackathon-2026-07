from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GTMEmailOctopusAdmissionDossierV2Tests(unittest.TestCase):
    def test_dossier_is_multi_source_cost_explicit_and_fail_closed(self) -> None:
        payload = json.loads((ROOT / "evidence/v10/gtm-emailoctopus-admission-dossier-v2.json").read_text())
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        expected = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, expected)
        self.assertEqual(payload["source_count"], 7)
        self.assertGreaterEqual(payload["captured_source_count"], 6)
        self.assertGreaterEqual(payload["independent_captured_source_count"], 1)
        self.assertEqual(set(payload["cost_components"]), {"paid_media", "personnel", "tools", "creators", "channel_fees", "production"})
        self.assertGreaterEqual(payload["evidence_ready_gate_count"], 10)
        self.assertTrue(payload["gates"]["six_cost_components"].startswith("evidence_ready"))
        self.assertTrue(payload["gates"]["entity_and_episode_resolution"].startswith("evidence_ready"))
        self.assertTrue(payload["gates"]["cross_platform_duplicate_review"].startswith("evidence_ready"))
        self.assertEqual(payload["gates"]["named_human_exact_binding"], "pending_named_review")
        self.assertFalse(payload["duplicate_screen"]["exact_content_mirror_detected"])
        self.assertFalse(payload["duplicate_screen"]["additional_case_episode_collision_detected"])
        claims = sum((row.get("targeted_claim_windows", []) for row in payload["sources"]), [])
        self.assertGreaterEqual(len(claims), 10)
        self.assertTrue(all(hashlib.sha256(row["bounded_exact_excerpt"].encode()).hexdigest() == row["excerpt_sha256"] for row in claims))
        self.assertEqual(payload["formal_candidate_quota_credit"], 0)
        self.assertFalse(payload["automatic_promotion_allowed"])
        self.assertTrue(all(row.get("raw_page_retained") is False for row in payload["sources"] if row["capture_status"] == "captured_and_bounded"))


if __name__ == "__main__":
    unittest.main()
