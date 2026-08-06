from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_text_named_pk_challenger import (
    EXPECTED_PRODUCTS,
    TextNamedPKChallengerError,
    compile_candidate,
    compile_row_portfolio,
    verify_row_portfolio,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMTextNamedPKChallengerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/codex-text-named-pk-super-challenger-v1.json").read_text(encoding="utf-8"))
        self.ledger = json.loads((ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json").read_text(encoding="utf-8"))

    def test_four_real_assets_bind_all_ten_named_products_without_claiming_wins(self) -> None:
        payload = compile_row_portfolio(compile_candidate(self.config), self.ledger)
        verify_row_portfolio(payload)
        self.assertEqual(set(payload["candidate"]["assets"]), {"linkedin", "partner_community", "landing_hero", "lifecycle_email"})
        self.assertEqual(tuple(row["reference_product"] for row in payload["rows"]), EXPECTED_PRODUCTS)
        self.assertTrue(all(row["opponent_specific_stress_test"] for row in payload["rows"]))
        self.assertEqual(payload["candidate_level_1_pass_count"], 10)
        self.assertEqual(payload["authorized_named_product_baseline_count"], 0)
        self.assertEqual(payload["completed_named_product_pk_count"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        self.assertFalse(payload["four_a_quality_proven"])

    def test_claim_drift_and_release_escape_fail_closed(self) -> None:
        broken = json.loads(json.dumps(self.config))
        broken["assets"]["linkedin"]["body"] = broken["assets"]["linkedin"]["body"].replace(
            broken["frozen_brief"]["approved_claim"], "A broader unsupported claim."
        )
        with self.assertRaisesRegex(TextNamedPKChallengerError, "approved claim"):
            compile_candidate(broken)
        broken = json.loads(json.dumps(self.config))
        broken["assets"]["landing_hero"]["release_state"] = "published"
        with self.assertRaisesRegex(TextNamedPKChallengerError, "human review"):
            compile_candidate(broken)

    def test_v2_replaces_feature_explanation_with_one_visible_campaign_act(self) -> None:
        config = json.loads(
            (ROOT / "config/codex-text-named-pk-super-challenger-v2.json").read_text(encoding="utf-8")
        )
        candidate = compile_candidate(config)
        self.assertEqual(candidate["strategic_core"]["campaign_name"], "Delete One Line")
        self.assertIn("We deleted the sentence our launch needed most.", candidate["assets"]["linkedin"]["hook"])
        self.assertIn("A strong counterexample changes the rule", candidate["assets"]["partner_community"]["body"])
        self.assertEqual(candidate["assets"]["landing_hero"]["headline"], "Delete one line.")
        self.assertIn("One sentence. One witness. Five minutes.", candidate["assets"]["lifecycle_email"]["preview"])
        self.assertTrue(all(asset["release_state"] == "draft_pending_named_human_review" for asset in candidate["assets"].values()))
        portfolio = compile_row_portfolio(candidate, self.ledger)
        self.assertEqual(portfolio["completed_named_product_pk_count"], 0)
        self.assertEqual(portfolio["candidate_win_count"], 0)


if __name__ == "__main__":
    unittest.main()
