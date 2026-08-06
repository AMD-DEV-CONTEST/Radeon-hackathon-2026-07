from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "artifacts/gtm-emailoctopus-named-review-v2"


class GTMEmailOctopusNamedReviewWorkbenchV2Tests(unittest.TestCase):
    def test_workbench_is_operator_gated_and_zero_credit(self) -> None:
        page = (WORKBENCH / "index.html").read_text()
        manifest = json.loads((WORKBENCH / "manifest.json").read_text())
        proposal = json.loads((ROOT / "evidence/v10/gtm-emailoctopus-named-review-proposal-v2.json").read_text())
        unsigned = dict(manifest)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(supplied, hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        self.assertEqual(manifest["source_proposal_sha256"], proposal["content_sha256"])
        self.assertEqual(manifest["html_sha256"], hashlib.sha256(page.encode()).hexdigest())
        self.assertFalse(manifest["reviewer_prefilled"])
        self.assertFalse(manifest["automatic_promotion_allowed"])
        self.assertEqual(manifest["formal_candidate_quota_credit"], 0)
        self.assertIn('id="reviewer"', page)
        self.assertIn('id="inspected"', page)
        self.assertIn('id="bind"', page)
        self.assertIn('button id="download" disabled', page)
        self.assertIn("submit_for_admission_gate", page)
        self.assertIn("formal_candidate_quota_credit:0", page)


if __name__ == "__main__":
    unittest.main()
