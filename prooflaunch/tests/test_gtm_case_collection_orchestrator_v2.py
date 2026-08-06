from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_case_collection_orchestrator_v2 import (
    GTMCaseCollectionOrchestratorError,
    compile_case_collection_orchestrator,
    verify_case_collection_orchestrator,
)
from prooflaunch_remix.gtm_case_evidence_funnel_v2 import (
    build_case_evidence_funnel_standard,
    compile_case_evidence_funnel_coverage,
)


class GTMCaseCollectionOrchestratorV2Tests(unittest.TestCase):
    def _payload(self) -> dict:
        standard = build_case_evidence_funnel_standard()
        coverage = compile_case_evidence_funnel_coverage(standard, [], [], [], [])
        oss = {
            "content_sha256": "a" * 64,
            "candidates": [{
                "platforms": ["linkedin", "youtube", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon", "podcast_rss", "owned_blog_newsletter"],
                "admission_decision": "production_admitted", "access_mode": "ordinary_public_pages_or_protocol", "runtime_proven": True,
                "repository": "https://github.com/example/adapter", "revision": "abc", "license_spdx": "MIT", "integration_role": "source_adapter_candidate",
            }],
        }
        return compile_case_collection_orchestrator(standard, coverage, oss)

    def test_builds_81_workstreams_16200_slots_and_7776_jobs(self) -> None:
        payload = self._payload()
        verify_case_collection_orchestrator(payload)
        self.assertEqual(payload["workstream_count"], 81)
        self.assertEqual(payload["case_slot_count"], 16200)
        self.assertEqual(payload["collection_job_count"], 7776)
        self.assertEqual(len(payload["priority_subvertical_ids"]), 10)
        self.assertTrue(all(slot["quota_credit"] == 0 for slot in payload["case_slots"]))

    def test_tamper_and_fake_slot_completion_fail_closed(self) -> None:
        payload = self._payload()
        fake = copy.deepcopy(payload)
        fake["case_slots"][0]["quota_credit"] = 1
        fake.pop("content_sha256")
        import hashlib, json
        fake["content_sha256"] = hashlib.sha256(json.dumps(fake, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.assertRaisesRegex(GTMCaseCollectionOrchestratorError, "quota credit"):
            verify_case_collection_orchestrator(fake)


if __name__ == "__main__":
    unittest.main()
