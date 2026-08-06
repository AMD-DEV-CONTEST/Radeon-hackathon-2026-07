from __future__ import annotations

import copy
import hashlib
import unittest

from prooflaunch_remix.gtm_case_claim_surface_v2 import compile_case_claim_surfaces
from prooflaunch_remix.gtm_gold_case_discovery_v2 import compile_gold_case_discovery
from prooflaunch_remix.gtm_gold_lead_review_queue_v2 import (
    GTMGoldLeadReviewQueueError,
    compile_gold_lead_review_queue,
    verify_gold_lead_review_queue,
)
from prooflaunch_remix.gtm_public_source_capture import FetchResponse, capture_public_sources


DIRECTORY = """
<li class="csl-directory-cards__card" data-industry="Manufacturing" data-size="25-200 employees"
 data-products="[Marketing Hub]" data-usecases="[Build Pipeline]" data-sort="[Newest]">
 <img alt="Acme"><h3 class="csl-card-title">Acme grows qualified pipeline 137%</h3>
 <a href="https://example.com/case-studies/acme">Read more</a></li>
"""
CASE = """
<main><p>In 2026 Acme launched a technical content and email workflow.</p>
<p>The team of 12 employees used a bounded low budget with one agency.</p>
<p>Within 6 months qualified pipeline grew 137% from baseline.</p></main>
"""


class GTMGoldLeadReviewQueueV2Tests(unittest.TestCase):
    def _inputs(self) -> tuple[dict, dict, dict]:
        directory_hash = hashlib.sha256(DIRECTORY.encode()).hexdigest()
        discovery = compile_gold_case_discovery([{
            "source_family_id": "hubspot_case_directory",
            "source_url": "https://example.com/case-studies/directory",
            "captured_at": "2026-08-05T12:00:00Z",
            "content_sha256": directory_hash,
            "html_text": DIRECTORY,
        }], research_cutoff="2026-08-05")
        capture = capture_public_sources(
            [{"url": "https://example.com/case-studies/acme"}],
            captured_at="2026-08-05T12:00:00Z",
            fetcher=lambda url: FetchResponse(200, url, "text/html", CASE.encode()),
            robots_checker=lambda url: ("allowed", True),
        )
        surfaces = compile_case_claim_surfaces(discovery, [{
            "source_url": "https://example.com/case-studies/acme",
            "captured_at": "2026-08-05T12:00:00Z",
            "content_sha256": hashlib.sha256(CASE.encode()).hexdigest(),
            "html_text": CASE,
        }])
        return discovery, capture, surfaces

    def test_prioritizes_four_surface_lead_without_minting_credit(self) -> None:
        payload = compile_gold_lead_review_queue(*self._inputs())
        verify_gold_lead_review_queue(payload)
        self.assertEqual(payload["review_item_count"], 1)
        self.assertEqual(payload["human_binding_ready_count"], 1)
        self.assertEqual(payload["records"][0]["quota_credit"], 0)
        self.assertIn("six_component_cost_completeness", payload["records"][0]["blocking_requirements"])
        equipment = next(row for row in payload["subvertical_queues"] if row["subvertical_id"].endswith("industrial_equipment"))
        self.assertEqual(equipment["status"], "source_coverage_gap")

    def test_tampered_credit_fails_closed(self) -> None:
        payload = compile_gold_lead_review_queue(*self._inputs())
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["quota_credit"] = 1
        with self.assertRaisesRegex(GTMGoldLeadReviewQueueError, "seal"):
            verify_gold_lead_review_queue(tampered)


if __name__ == "__main__":
    unittest.main()
