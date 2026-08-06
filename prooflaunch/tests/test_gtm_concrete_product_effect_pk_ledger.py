from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.compile_gtm_concrete_product_effect_pk_ledger import CATEGORY_EXECUTION, build


ROOT = Path(__file__).resolve().parents[1]


class GTMConcreteProductEffectPKLedgerTests(unittest.TestCase):
    def test_every_category_has_ten_concrete_product_rows(self) -> None:
        payload = build()
        self.assertEqual(payload["category_count"], 13)
        self.assertEqual(payload["reference_product_row_count"], 130)
        counts: dict[str, int] = {}
        for row in payload["product_pk_rows"]:
            counts[row["category_id"]] = counts.get(row["category_id"], 0) + 1
            self.assertTrue(row["same_brief_task"])
            self.assertTrue(row["effect_pk_question"])
            self.assertGreaterEqual(len(row["quality_axes"]), 7)
            self.assertTrue(row["open_source_reuse"])
            self.assertTrue(row["internal_same_brief_opponent_compiled"])
            self.assertFalse(row["named_product_baseline_present"])
            self.assertFalse(row["effect_alignment_achieved"])
        self.assertEqual(set(counts), set(CATEGORY_EXECUTION))
        self.assertEqual(set(counts.values()), {10})
        self.assertEqual(
            payload["portfolio"]["categories_with_internal_same_brief_opponent"],
            13,
        )
        self.assertEqual(
            payload["portfolio"]["categories_with_named_product_baseline"],
            0,
        )

    def test_open_source_reuse_is_revision_and_license_pinned(self) -> None:
        payload = build()
        for category in payload["categories"]:
            for project in category["open_source_projects"]:
                self.assertRegex(project["revision"], r"^[0-9a-f]{40}$")
                self.assertTrue(project["license"])
                self.assertTrue(project["url"].startswith("https://github.com/"))

    def test_missing_artifact_never_becomes_effect_proof(self) -> None:
        payload = build()
        advertising = next(item for item in payload["categories"] if item["category_id"] == "advertising_activation")
        # The challenger may still be generating; either state remains explicitly non-promotional.
        self.assertFalse(advertising["effect_alignment_achieved"])
        self.assertEqual(payload["portfolio"]["completed_product_pk_rows"], 0)

    def test_sealed_output_digest_matches(self) -> None:
        path = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
        if not path.is_file():
            self.skipTest("compiled ledger not present")
        payload = json.loads(path.read_text(encoding="utf-8"))
        supplied = payload.pop("content_sha256")
        import hashlib
        expected = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(supplied, expected)


if __name__ == "__main__":
    unittest.main()
