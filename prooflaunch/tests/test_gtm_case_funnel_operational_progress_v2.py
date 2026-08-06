from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GTMCaseFunnelOperationalProgressV2Tests(unittest.TestCase):
    def test_operational_funnel_preserves_formal_zero_and_visible_work(self) -> None:
        payload = json.loads((ROOT / "evidence/v10/gtm-case-funnel-operational-progress-v2.json").read_text())
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        observed = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, observed)
        self.assertEqual(payload["formal_target"], 16_200)
        self.assertEqual(payload["public_lead_count"], 1_741)
        self.assertEqual(payload["review_packet_count"], 382)
        self.assertEqual(payload["machine_ready_for_named_review_count"], 247)
        self.assertEqual(payload["one_named_review_away_count"], 9)
        self.assertEqual(payload["p0_machine_closure"]["percent"], 90.0)
        self.assertEqual(payload["p0_triaged_count"], 10)
        self.assertEqual(payload["p0_blocked_count"], 1)
        self.assertEqual(payload["progress_lenses"]["public_discovery_coverage"]["percent"], 10.747)
        self.assertEqual(payload["progress_lenses"]["machine_ready_coverage"]["percent"], 1.525)
        self.assertTrue(payload["metric_policy"]["0_over_16200_is_not_a_complete_operational_status"])
        self.assertTrue(payload["metric_policy"]["formal_zero_must_not_be_used_as_the_sole_progress_headline"])

    def test_html_exposes_first_real_closure_action(self) -> None:
        page = (ROOT / "artifacts/gtm-case-funnel-operational-progress-v2/index.html").read_text()
        self.assertIn("10/11", page)
        self.assertIn("实名复核页", page)
        self.assertIn("admit_gtm_emailoctopus_case_v2.py", page)
        self.assertIn("admit_gtm_buffer_case_v2.py", page)
        self.assertIn("admit_gtm_flodesk_case_v2.py", page)
        self.assertIn("admit_gtm_postbridge_case_v2.py", page)
        self.assertIn("admit_gtm_parqet_case_v2.py", page)
        self.assertIn("admit_gtm_spendbase_case_v2.py", page)
        self.assertIn("admit_gtm_barn2_case_v2.py", page)
        self.assertIn("admit_gtm_rightmessage_case_v2.py", page)
        self.assertIn("admit_gtm_socially_case_v2.py", page)
        self.assertIn("9/10", page)
        self.assertIn("P0 已完成 10/10", page)
        self.assertIn("Automatio · 9/11 blocker", page)
        self.assertIn("不是 0 进度", page)
        self.assertIn("gtm-seven-case-batch-review-v2", page)


if __name__ == "__main__":
    unittest.main()
