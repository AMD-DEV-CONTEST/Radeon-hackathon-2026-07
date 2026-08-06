from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import review_packet_digest
from prooflaunch_remix.gtm_case_candidate_binding_v2 import GATES
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import REQUIRED_FIELD_BINDINGS, SIX_COST_COMPONENTS


ROOT = Path(__file__).resolve().parents[1]


class GTMEmailOctopusNamedReviewProposalV2Tests(unittest.TestCase):
    def test_proposal_is_complete_prefill_but_not_fabricated_review(self) -> None:
        payload = json.loads((ROOT / "evidence/v10/gtm-emailoctopus-named-review-proposal-v2.json").read_text())
        ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        expected = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, expected)
        packet = next(row for row in ledger["records"] if row["review_packet_id"] == payload["review_packet_id"])
        self.assertEqual(payload["review_packet_sha256"], review_packet_digest(packet))
        self.assertEqual(set(payload["field_bindings"]), set(REQUIRED_FIELD_BINDINGS))
        self.assertEqual(set(payload["cost_components"]), set(SIX_COST_COMPONENTS))
        self.assertEqual(set(payload["gate_evidence"]), set(GATES))
        self.assertEqual(sum(str(v).startswith("evidence_ready") for v in payload["gate_evidence"].values()), 10)
        self.assertGreaterEqual(len(payload["exact_primary_claim_bindings"]), 5)
        self.assertGreaterEqual(len(payload["secondary_claim_bindings"]), 10)
        self.assertTrue(all(row["source_url"] == payload["source_url"] for row in payload["exact_primary_claim_bindings"]))
        self.assertTrue(all(hashlib.sha256(row["exact_excerpt"].encode()).hexdigest() == row["excerpt_sha256"] for row in payload["exact_primary_claim_bindings"]))
        self.assertIsNone(payload["reviewer_name"])
        self.assertIsNone(payload["reviewed_at"])
        self.assertFalse(payload["source_inspected"])
        self.assertEqual(payload["formal_candidate_quota_credit"], 0)
        self.assertFalse(payload["automatic_promotion_allowed"])


if __name__ == "__main__":
    unittest.main()
