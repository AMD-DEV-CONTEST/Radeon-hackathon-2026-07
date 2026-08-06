from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_text_super_challenger_export import export_text_super_challenger


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"


class TextSuperChallengerExportTests(unittest.TestCase):
    def test_exports_real_source_hidden_four_asset_pack(self) -> None:
        portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate"
            manifest = export_text_super_challenger(portfolio=portfolio, output_root=output)
            self.assertEqual(manifest["asset_count"], 4)
            self.assertEqual(manifest["named_product_target_count"], 10)
            self.assertEqual(manifest["completed_named_product_pk_count"], 0)
            self.assertFalse(manifest["release_eligible"])
            dossier = (output / "source-hidden-review-dossier.html").read_text(encoding="utf-8")
            self.assertIn("The Rejection Rule Is the Product", dossier)
            self.assertNotIn("Codex", dossier)
            for opponent in ("ChatGPT", "Claude", "Gemini", "Jasper", "Writesonic"):
                self.assertNotIn(opponent, dossier)
            channel = json.loads((output / "channel-copy.json").read_text(encoding="utf-8"))
            self.assertTrue(channel["primary"])
            self.assertTrue(channel["secondary"])
            self.assertEqual(channel["release_state"], "draft_pending_named_human_review")


if __name__ == "__main__":
    unittest.main()
