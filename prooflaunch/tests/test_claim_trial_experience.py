from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ClaimTrialExperienceTests(unittest.TestCase):
    def test_self_trial_rejects_unsupported_superiority(self) -> None:
        module = "./artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/claim-trial-engine.mjs"
        program = f'''import {{tryClaim}} from "{module}";
const result=tryClaim({{claim:"A 4A-grade GTM employee that makes any brand go viral.",evidence:"",source:"",sample:"none",period:"none",limitations:""}});
if(result.verdict!=="NO WITNESS") process.exit(1);
if(!result.flags.includes("4a-grade") || !result.flags.includes("any brand") || !result.flags.includes("viral")) process.exit(2);
if(!result.missing.includes("named source") || !result.missing.includes("material limitation")) process.exit(3);'''
        result = subprocess.run(["node", "--input-type=module", "-e", program], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_supported_branch_requires_a_real_evidence_shape(self) -> None:
        module = "./artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/claim-trial-engine.mjs"
        program = f'''import {{tryClaim}} from "{module}";
const result=tryClaim({{claim:"The workflow generated review-ready draft packs for the frozen cases.",evidence:"The workflow generated review-ready draft packs for 26 frozen internal fixtures",source:"sealed local fixture report",sample:"independent",period:"current",limitations:"Internal fixtures only; no publication or market effect was observed"}});
if(result.verdict!=="PROVISIONALLY SUPPORTED") process.exit(1);
if(result.proof<7 || result.missing.length!==0) process.exit(2);
if(!result.rewrite.includes("according to sealed local fixture report")) process.exit(3);'''
        result = subprocess.run(["node", "--input-type=module", "-e", program], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_receipt_preserves_effect_truth_boundary(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1"
        receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
        self.assertTrue(receipt["self_claim_rejected"])
        self.assertFalse(receipt["human_preference_observed"])
        self.assertFalse(receipt["production_effect_observed"])
        self.assertEqual(receipt["completed_named_product_pk_count"], 0)
        self.assertEqual(receipt["named_product_win_count"], 0)
        page = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn("Put the claim on trial", page)
        self.assertIn("NO WITNESS", page)
        self.assertIn('src="claim-trial-browser.js"', page)
        self.assertTrue((root / "claim-trial-browser.js").is_file())
        self.assertTrue((root / "share-card-4x5.html").is_file())
        self.assertIn("if (shouldScroll)", (root / "claim-trial-browser.js").read_text(encoding="utf-8"))
        self.assertNotIn("fetch(", page)


if __name__ == "__main__":
    unittest.main()
