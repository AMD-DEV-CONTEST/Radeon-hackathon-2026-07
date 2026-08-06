from __future__ import annotations

import copy
import hashlib
import unittest

from prooflaunch_remix.gtm_case_claim_surface_v2 import (
    GTMCaseClaimSurfaceError,
    compile_case_claim_surfaces,
    extract_claim_surfaces,
    verify_case_claim_surfaces,
)
from prooflaunch_remix.gtm_gold_case_discovery_v2 import compile_gold_case_discovery


DIRECTORY_HTML = """
<li class="csl-directory-cards__card" data-industry="Manufacturing" data-size="25-200 employees"
 data-products="[Marketing Hub]" data-usecases="[Build Pipeline]" data-sort="[Newest]">
 <img alt="Acme"><h3 class="csl-card-title">Acme manufacturing case</h3>
 <a href="https://example.com/case-studies/acme">Read more</a>
</li>
"""

CASE_HTML = """
<html><head><meta property="og:title" content="Acme case"></head><body>
<nav><p>Customers get 129% more leads in generic navigation copy.</p></nav>
<main>
<h1>Acme manufacturing case</h1>
<p>In 2026 the team launched a technical email and content workflow.</p>
<p>A team of 12 employees used a low budget and one specialist agency.</p>
<p>Within 6 months, qualified pipeline grew 137% from the stated baseline.</p>
</main>
</body></html>
"""


class GTMCaseClaimSurfaceV2Tests(unittest.TestCase):
    def _discovery(self) -> dict:
        return compile_gold_case_discovery([{
            "source_family_id": "hubspot_case_directory",
            "source_url": "https://example.com/case-studies/directory",
            "captured_at": "2026-08-05T12:00:00Z",
            "content_sha256": hashlib.sha256(DIRECTORY_HTML.encode()).hexdigest(),
            "html_text": DIRECTORY_HTML,
        }], research_cutoff="2026-08-05")

    def test_extracts_four_bounded_surfaces_and_suppresses_navigation(self) -> None:
        result = extract_claim_surfaces(CASE_HTML)
        self.assertTrue(all(result["fragment_counts"][category] > 0 for category in result["fragment_counts"]))
        excerpts = " ".join(
            fragment["bounded_exact_excerpt"]
            for rows in result["fragments"].values()
            for fragment in rows
        )
        self.assertNotIn("generic navigation", excerpts)
        self.assertLessEqual(result["bounded_excerpt_word_count"], 200)

    def test_compiles_zero_credit_human_review_queue(self) -> None:
        discovery = self._discovery()
        payload = compile_case_claim_surfaces(discovery, [{
            "source_url": "https://example.com/case-studies/acme",
            "captured_at": "2026-08-05T12:00:00Z",
            "content_sha256": hashlib.sha256(CASE_HTML.encode()).hexdigest(),
            "html_text": CASE_HTML,
        }])
        verify_case_claim_surfaces(payload)
        self.assertEqual(payload["four_surface_signal_count"], 1)
        self.assertEqual(payload["records"][0]["quota_credit"], 0)

    def test_hash_mismatch_and_tamper_fail_closed(self) -> None:
        discovery = self._discovery()
        with self.assertRaisesRegex(GTMCaseClaimSurfaceError, "hash"):
            compile_case_claim_surfaces(discovery, [{
                "source_url": "https://example.com/case-studies/acme",
                "content_sha256": "0" * 64,
                "html_text": CASE_HTML,
            }])
        payload = compile_case_claim_surfaces(discovery, [{
            "source_url": "https://example.com/case-studies/acme",
            "captured_at": "2026-08-05T12:00:00Z",
            "content_sha256": hashlib.sha256(CASE_HTML.encode()).hexdigest(),
            "html_text": CASE_HTML,
        }])
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["quota_credit"] = 1
        with self.assertRaisesRegex(GTMCaseClaimSurfaceError, "seal"):
            verify_case_claim_surfaces(tampered)


if __name__ == "__main__":
    unittest.main()
