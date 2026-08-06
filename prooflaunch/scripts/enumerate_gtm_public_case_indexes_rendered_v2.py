#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_public_case_index_enumerator_v2 import (
    enumerate_public_case_indexes,
    verify_public_case_index_enumeration,
)
from prooflaunch_remix.gtm_public_source_capture import FetchResponse, USER_AGENT


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/gtm_case_funnel_v2/public-case-index-source-registry-v2.json"
OUTPUT = ROOT / "evidence/v10/gtm-public-case-index-enumeration-rendered-v2.json"
LEADS = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave5-rendered-indexes-v2.json"
MAX_RENDERED_BYTES = 5_000_000


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    sources = [
        {
            **row,
            "access_method": "credential_free_public_browser_render",
            "client_side_rendered": True,
        }
        for row in registry["sources"]
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-US")

        def fetch_rendered(url: str) -> FetchResponse:
            page = context.new_page()
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "media", "font"}
                else route.continue_(),
            )
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                for _ in range(6):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(500)
                body = page.content().encode("utf-8")
                if len(body) > MAX_RENDERED_BYTES:
                    raise ValueError("rendered index exceeds bounded capture limit")
                return FetchResponse(
                    status=int(response.status if response is not None else 200),
                    final_url=page.url,
                    content_type="text/html; rendered=playwright",
                    body=body,
                )
            finally:
                page.close()

        payload = enumerate_public_case_indexes(sources, fetcher=fetch_rendered)
        browser.close()

    verify_public_case_index_enumeration(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    lead_set = {
        "schema": "ProofLaunchGTMAllSubverticalPublicLeadSetV2",
        "wave_id": "wave5-public-case-indexes-rendered",
        "record_count": len(payload["records"]),
        "source_enumeration_sha256": payload["content_sha256"],
        "records": payload["records"],
        "formal_candidate_quota_credit": 0,
        "truth_boundary": payload["truth_boundary"],
    }
    atomic_write_text(LEADS, json.dumps(lead_set, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "leads": str(LEADS),
        "source_count": payload["source_count"],
        "status_counts": payload["status_counts"],
        "enumerated_unique_lead_count": payload["enumerated_unique_lead_count"],
        "formal_candidate_quota_credit": 0,
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
