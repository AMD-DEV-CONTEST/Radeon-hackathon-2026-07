from __future__ import annotations
import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class GTMAutomatioBlockerDossierV2Tests(unittest.TestCase):
    def test_budget_gap_blocks_admission_without_erasing_evidence(self):
        payload=json.loads((ROOT/"evidence/v10/gtm-automatio-blocker-dossier-v2.json").read_text()); unsigned=dict(payload); supplied=unsigned.pop("content_sha256"); observed=hashlib.sha256(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(); self.assertEqual(supplied,observed); self.assertEqual(payload["captured_source_count"],7); self.assertGreaterEqual(payload["independent_captured_source_count"],3); self.assertEqual(payload["evidence_ready_gate_count"],9); self.assertEqual(payload["blocking_gate_count"],2); self.assertTrue(payload["gates"]["source_bound_budget_tier"].startswith("blocked")); self.assertEqual(payload["formal_candidate_quota_credit"],0); self.assertTrue(payload["replacement_lane_required"])
    def test_no_cost_is_silently_relabelled_zero(self):
        payload=json.loads((ROOT/"evidence/v10/gtm-automatio-blocker-dossier-v2.json").read_text()); self.assertTrue(all(row["amount_usd"] is None for row in payload["cost_components"].values())); self.assertNotIn("zero_paid", json.dumps(payload))
if __name__=="__main__": unittest.main()
