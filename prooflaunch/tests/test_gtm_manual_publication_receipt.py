from __future__ import annotations

import unittest
from urllib.parse import urlencode

from prooflaunch_remix.gtm_manual_publication_receipt import (
    ManualPublicationReceiptError,
    compile_manual_publication_receipt,
)


class ManualPublicationReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tags = {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "launch-1",
            "utm_content": "proof-candidate",
            "pl_experiment": "experiment-1",
            "pl_arm": "candidate",
            "pl_run": "run-0123456789abcdef01234567",
        }
        self.asset_sha = "a" * 64
        self.payload = {
            "receipt_id": "pub-0123456789abcdef01234567",
            "channel": "linkedin_organic",
            "asset_name": "channel-copy.json",
            "asset_sha256": self.asset_sha,
            "public_url": "https://www.linkedin.com/posts/example?" + urlencode(self.tags),
            "published_at": "2026-08-02T14:30:00-04:00",
            "source_kind": "operator_attestation",
            "source_reference_sha256": "b" * 64,
            "operator_attested": True,
        }

    def compile(self, payload=None):
        return compile_manual_publication_receipt(
            payload or self.payload,
            run_id="run-0123456789abcdef01234567",
            campaign_id="campaign-1",
            experiment_id="experiment-1",
            strategy_plan_sha256="c" * 64,
            attribution_plan_sha256="d" * 64,
            candidate_tags=self.tags,
            allowed_assets={"channel-copy.json": self.asset_sha},
            authenticated_operator="named-operator",
        )

    def test_receipt_is_bound_and_does_not_claim_platform_verification(self) -> None:
        receipt = self.compile()
        self.assertEqual(receipt["arm"], "candidate")
        self.assertEqual(receipt["operator_identity"], "named-operator")
        self.assertFalse(receipt["publication_performed_by_prooflaunch"])
        self.assertFalse(receipt["platform_delivery_verified"])
        self.assertFalse(receipt["effect_claim_eligible"])
        self.assertRegex(receipt["content_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(receipt, self.compile())

    def test_rejects_missing_or_drifted_attribution_tags(self) -> None:
        payload = dict(self.payload)
        payload["public_url"] = "https://example.com/post?pl_arm=baseline"
        with self.assertRaisesRegex(
            ManualPublicationReceiptError, "exact candidate attribution tag"
        ):
            self.compile(payload)

    def test_rejects_private_url_wrong_asset_and_naive_time(self) -> None:
        for patch in (
            {"public_url": "https://127.0.0.1/post?" + urlencode(self.tags)},
            {"asset_sha256": "e" * 64},
            {"published_at": "2026-08-02T14:30:00"},
            {"operator_attested": False},
        ):
            payload = {**self.payload, **patch}
            with self.assertRaises(ManualPublicationReceiptError):
                self.compile(payload)


if __name__ == "__main__":
    unittest.main()
