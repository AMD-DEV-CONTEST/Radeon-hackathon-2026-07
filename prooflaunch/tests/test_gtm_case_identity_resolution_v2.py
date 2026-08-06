from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_case_identity_resolution_v2 import (
    GTMCaseIdentityResolutionError,
    compile_case_identity_resolution,
    verify_case_identity_resolution,
)


def _record(record_id: str, **overrides: object) -> dict:
    row = {
        "record_id": record_id,
        "company": "Acme Manufacturing, Inc.",
        "company_domain": "https://www.acme.example/about",
        "product": "Industrial filtration system",
        "campaign_or_motion": "Engineer education and specification discovery",
        "primary_market": "north_america",
        "observed_start": "2025-01-01",
        "observed_end": "2025-06-30",
        "source_urls": [f"https://evidence.example/{record_id}"],
        "quota_credit": 1,
    }
    row.update(overrides)
    return row


class GTMCaseIdentityResolutionV2Tests(unittest.TestCase):
    def test_exact_cross_platform_episode_counts_once(self) -> None:
        payload = compile_case_identity_resolution([_record("page-a"), _record("page-b")])
        verify_case_identity_resolution(payload)
        self.assertEqual(payload["unique_entity_count"], 1)
        self.assertEqual(payload["unique_episode_count"], 1)
        self.assertEqual(payload["exact_mirror_count"], 1)
        self.assertEqual(sum(row["resolved_quota_credit"] for row in payload["records"]), 1)

    def test_fuzzy_motion_is_flagged_but_not_auto_merged(self) -> None:
        payload = compile_case_identity_resolution([
            _record("page-a"),
            _record(
                "page-b",
                campaign_or_motion="Engineer education specification discovery program",
                observed_start="2025-07-01",
                observed_end="2025-12-31",
            ),
        ], fuzzy_threshold=0.75)
        verify_case_identity_resolution(payload)
        self.assertEqual(payload["unique_episode_count"], 2)
        self.assertEqual(payload["fuzzy_review_count"], 1)
        self.assertFalse(payload["fuzzy_review_flags"][0]["automatic_merge_allowed"])

    def test_tampered_mirror_credit_fails_closed(self) -> None:
        payload = compile_case_identity_resolution([_record("page-a"), _record("page-b")])
        tampered = copy.deepcopy(payload)
        mirror = next(row for row in tampered["records"] if row["resolution_status"] == "exact_episode_mirror")
        mirror["resolved_quota_credit"] = 1
        tampered.pop("content_sha256")
        import hashlib, json
        tampered["content_sha256"] = hashlib.sha256(json.dumps(tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.assertRaisesRegex(GTMCaseIdentityResolutionError, "mirror"):
            verify_case_identity_resolution(tampered)


if __name__ == "__main__":
    unittest.main()
