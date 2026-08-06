from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GTM40AssetInteractiveLandingTests(unittest.TestCase):
    def test_landing_is_local_interactive_and_truth_safe(self) -> None:
        output = ROOT / "artifacts/gtm-last-mile-pk-v1/interactive-landing-v1-40-asset-interview"
        receipt = json.loads((output / "interactive-landing-receipt.json").read_text(encoding="utf-8"))
        page = (output / "index.html").read_text(encoding="utf-8")
        self.assertEqual(receipt["asset_card_count"], 40)
        self.assertEqual(receipt["blocked_card_count"], 39)
        self.assertEqual(receipt["review_card_count"], 1)
        self.assertEqual(receipt["network_call_count"], 0)
        self.assertEqual(receipt["model_call_count"], 0)
        self.assertFalse(receipt["external_publish_executed"])
        self.assertTrue(receipt["human_release_required"])
        self.assertFalse(receipt["human_preference_observed"])
        self.assertEqual(receipt["completed_named_product_pk_count"], 0)
        self.assertEqual(receipt["candidate_win_count"], 0)
        self.assertEqual(receipt["evaluator"]["runtime_case_count"], 4)
        self.assertEqual(page.count('class="asset-card '), 40)
        self.assertNotIn("fetch(", page)
        self.assertNotIn("XMLHttpRequest", page)
        self.assertNotIn("WebSocket", page)
        self.assertIn("INTERVIEW THIS SENTENCE", page)
        self.assertIn('src="claim-interview.mjs"', page)

    def test_claim_interview_runtime_covers_all_decision_branches(self) -> None:
        module = "./artifacts/gtm-last-mile-pk-v1/interactive-landing-v1-40-asset-interview/claim-interview.mjs"
        program = f"""import {{ evaluateClaim }} from '{module}';
const cases = [
  [{{claim:'',evidencePresent:false,ownerPresent:false}}, 'BLOCK', 'EMPTY'],
  [{{claim:'x',evidencePresent:false,ownerPresent:false}}, 'BLOCK', 'HYPOTHESIS'],
  [{{claim:'x',evidencePresent:true,ownerPresent:false}}, 'BLOCK', 'INFERENCE'],
  [{{claim:'x',evidencePresent:true,ownerPresent:true}}, 'REVIEW', 'UNVERIFIED']
];
for (const [input, decision, state] of cases) {{ const out=evaluateClaim(input); if(out.decision!==decision || out.state!==state) process.exit(1); }}
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
