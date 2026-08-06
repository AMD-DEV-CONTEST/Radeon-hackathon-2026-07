from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GTMFourCaseBatchReviewV2Tests(unittest.TestCase):
    def test_manifest_and_page_preserve_human_gate(self) -> None:
        manifest = json.loads((ROOT / "artifacts/gtm-four-case-batch-review-v2/manifest.json").read_text())
        unsigned = dict(manifest)
        supplied = unsigned.pop("content_sha256")
        observed = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, observed)
        self.assertEqual(manifest["case_count"], 4)
        self.assertEqual(manifest["source_link_count"], 28)
        self.assertEqual(manifest["formal_candidate_quota_credit"], 0)
        page = (ROOT / "artifacts/gtm-four-case-batch-review-v2/index.html").read_text()
        self.assertIn("一次填写身份，四案仍逐案实质复核", page)
        self.assertIn("admit_gtm_four_case_batch_v2.py", page)
        self.assertIn("gtm-four-case-batch-review-intake-v2.json", page)


if __name__ == "__main__":
    unittest.main()
