from __future__ import annotations

import json
import copy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from prooflaunch_remix.gtm_platform_native_publication_audit import (  # noqa: E402
    compile_platform_native_publication_audit,
    publication_failures,
    verify_platform_native_publication_audit,
)


class GTMPlatformNativePublicationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1"
        cls.bundles = [
            (
                json.loads((root / "b2b-plan.json").read_text(encoding="utf-8")),
                json.loads(
                    (root / "b2b-local-gemma3-final-receipt.json").read_text(
                        encoding="utf-8"
                    )
                ),
            ),
            (
                json.loads((root / "b2c-plan.json").read_text(encoding="utf-8")),
                json.loads(
                    (root / "b2c-local-gemma3-v1-receipt.json").read_text(
                        encoding="utf-8"
                    )
                ),
            ),
        ]

    def test_real_local_drafts_receive_a_separate_publication_audit(self) -> None:
        audit = compile_platform_native_publication_audit(self.bundles)
        verify_platform_native_publication_audit(audit)
        self.assertEqual(audit["row_count"], 26)
        self.assertEqual(audit["b2b_row_count"], 13)
        self.assertEqual(audit["b2c_row_count"], 13)
        self.assertEqual(audit["human_review_completed_count"], 0)
        self.assertFalse(audit["external_publish_executed"])

    def test_placeholder_link_and_synthetic_content_fail_closed(self) -> None:
        b2b_plan, b2b_receipt = self.bundles[0]
        b2b_requests = {row["surface_id"]: row for row in b2b_plan["requests"]}
        linkedin = next(
            row for row in b2b_receipt["accepted_candidates"] if row["surface_id"] == "linkedin"
        )
        self.assertIn(
            "unresolved_placeholder_or_hypothetical_asset",
            publication_failures(
                linkedin, plan=b2b_plan, request=b2b_requests["linkedin"]
            ),
        )
        b2c_plan, b2c_receipt = self.bundles[1]
        b2c_requests = {row["surface_id"]: row for row in b2c_plan["requests"]}
        candidate = b2c_receipt["accepted_candidates"][0]
        self.assertIn(
            "synthetic_benchmark_is_not_publishable_product_content",
            publication_failures(
                candidate,
                plan=b2c_plan,
                request=b2c_requests[candidate["surface_id"]],
            ),
        )

    def test_unbound_case_tool_and_inline_media_link_fail_closed(self) -> None:
        plan, receipt = self.bundles[0]
        requests = {row["surface_id"]: row for row in plan["requests"]}
        candidate = copy.deepcopy(receipt["accepted_candidates"][0])
        candidate["body"] = [
            "I recently dug into a live brief from a $20M ARR company.",
            "image Link to a diagnostic tool, screen recording and personalized assessment.",
            "Submit a brief and receive a detailed provenance trace; the campaign generated few qualified leads.",
        ]
        failures = publication_failures(
            candidate,
            plan=plan,
            request=requests[candidate["surface_id"]],
        )
        self.assertIn("unresolved_placeholder_or_hypothetical_asset", failures)
        self.assertIn("unbound_case_or_tool_claim", failures)


if __name__ == "__main__":
    unittest.main()
