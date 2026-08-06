from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_case_candidate_binding_v2 import (
    GTMCaseCandidateBindingError,
    compile_case_candidate_binding_packets,
    verify_case_candidate_binding_packets,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMCaseCandidateBindingV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.discovery = json.loads((ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json").read_text())
        cls.capture = json.loads((ROOT / "evidence/v10/gtm-gold-case-public-source-capture-v2.json").read_text())
        cls.surfaces = json.loads((ROOT / "evidence/v10/gtm-gold-case-claim-surfaces-v2.json").read_text())
        cls.queue = json.loads((ROOT / "evidence/v10/gtm-gold-lead-review-queue-v2.json").read_text())

    def test_compiles_every_review_item_without_minting_candidate_credit(self) -> None:
        payload = compile_case_candidate_binding_packets(
            self.discovery, self.capture, self.surfaces, self.queue
        )
        verify_case_candidate_binding_packets(payload)
        self.assertEqual(payload["packet_count"], self.queue["review_item_count"])
        self.assertEqual(payload["candidate_quota_credit"], 0)
        self.assertTrue(all(row["quota_credit"] == 0 for row in payload["records"]))
        self.assertTrue(all(row["human_review_template"]["decision"] == "pending" for row in payload["records"]))

    def test_fabricated_human_review_or_excerpt_tamper_fails(self) -> None:
        payload = compile_case_candidate_binding_packets(
            self.discovery, self.capture, self.surfaces, self.queue
        )
        fabricated = copy.deepcopy(payload)
        fabricated["records"][0]["human_review_template"]["decision"] = "approved"
        fabricated.pop("content_sha256")
        from prooflaunch_remix.gtm_case_candidate_binding_v2 import _digest
        fabricated["content_sha256"] = _digest(fabricated)
        with self.assertRaisesRegex(GTMCaseCandidateBindingError, "human review"):
            verify_case_candidate_binding_packets(fabricated)

    def test_gate_and_blocker_drift_fails_even_after_resealing(self) -> None:
        payload = compile_case_candidate_binding_packets(
            self.discovery, self.capture, self.surfaces, self.queue
        )
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["admission_gates"]["source_bound_budget_tier_and_six_cost_components"] = True
        tampered["records"][0]["blocking_requirements"].remove(
            "source_bound_budget_tier_and_six_cost_components"
        )
        tampered.pop("content_sha256")
        from prooflaunch_remix.gtm_case_candidate_binding_v2 import _digest
        tampered["content_sha256"] = _digest(tampered)
        with self.assertRaisesRegex(GTMCaseCandidateBindingError, "auto-passed"):
            verify_case_candidate_binding_packets(tampered)


if __name__ == "__main__":
    unittest.main()
