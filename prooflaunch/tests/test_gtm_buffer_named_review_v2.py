from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GTMBufferNamedReviewV2Tests(unittest.TestCase):
    def test_proposal_is_sealed_complete_and_unreviewed(self) -> None:
        payload = json.loads((ROOT / "evidence/v10/gtm-buffer-named-review-proposal-v2.json").read_text())
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        observed = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, observed)
        self.assertEqual(len(payload["field_bindings"]), 15)
        self.assertEqual(len(payload["cost_components"]), 6)
        self.assertEqual(len(payload["gate_evidence"]), 11)
        self.assertEqual(sum(str(value).startswith("evidence_ready") for value in payload["gate_evidence"].values()), 10)
        self.assertIsNone(payload["reviewer_name"])
        self.assertEqual(payload["formal_candidate_quota_credit"], 0)

    def test_workbench_requires_substantive_named_interaction(self) -> None:
        page = (ROOT / "artifacts/gtm-buffer-named-review-v2/index.html").read_text()
        manifest = json.loads((ROOT / "artifacts/gtm-buffer-named-review-v2/manifest.json").read_text())
        self.assertIn("Buffer 实名准入复核", page)
        self.assertIn("全部绑定来源", page)
        self.assertIn("notes.value.trim().length>=20".replace("notes", "n"), page)
        self.assertIn("submit_for_admission_gate", page)
        self.assertFalse(manifest["reviewer_prefilled"])
        self.assertEqual(manifest["formal_candidate_quota_credit"], 0)


if __name__ == "__main__":
    unittest.main()
