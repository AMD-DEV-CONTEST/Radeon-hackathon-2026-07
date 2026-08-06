#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_public_source_capture import capture_public_sources, verify_public_source_capture
from prooflaunch_remix.gtm_wave1_discovery_leads_v2 import (
    compile_wave1_discovery_leads,
    verify_wave1_discovery_leads,
)


ROOT = Path(__file__).resolve().parents[1]


LEADS = [
    {"lead_id": "wave1-casio", "company": "Casio UK and Ireland", "provisional_subvertical_id": "b2b.industrial_climate.manufacturing", "provisional_company_scale": "enterprise_or_mass_brand", "source_url": "https://www.hubspot.com/case-studies/casio", "source_class": "official_platform", "discovery_rationale": "Manufacturing case with reported ecommerce, traffic, impression, and email-revenue outcomes; exact episode and resource scope remain unresolved."},
    {"lead_id": "wave1-mastermover", "company": "MasterMover", "provisional_subvertical_id": "b2b.industrial_climate.industrial_equipment", "provisional_company_scale": "mid_market", "source_url": "https://www.hubspot.com/case-studies/mastermover", "source_class": "official_platform", "discovery_rationale": "Industrial equipment case with reported MQL-to-SQL and deal-value outcomes; exact period and budget remain unresolved."},
    {"lead_id": "wave1-remax-romania", "company": "RE/MAX Romania", "provisional_subvertical_id": "b2b.industrial_climate.commercial_real_estate", "provisional_company_scale": "mid_market", "source_url": "https://www.hubspot.com/case-studies/re/max-romania-increased-leads-by-114-with-hubspot", "source_class": "official_platform", "discovery_rationale": "Real-estate case with reported lead and customer changes; attribution, period, and resource scope require inspection."},
    {"lead_id": "wave1-avison-young", "company": "Avison Young", "provisional_subvertical_id": "b2b.industrial_climate.commercial_real_estate", "provisional_company_scale": "enterprise_or_mass_brand", "source_url": "https://www.hubspot.com/case-studies/avisonyoung", "source_class": "official_platform", "discovery_rationale": "Commercial real-estate operating case with reported CRM adoption and revenue-tracking coverage; GTM outcome linkage remains unresolved."},
    {"lead_id": "wave1-dryft", "company": "Dryft", "provisional_subvertical_id": "b2b.industrial_climate.engineering_construction", "provisional_company_scale": "unresolved", "source_url": "https://www.hubspot.com/case-studies/dryft", "source_class": "official_platform", "discovery_rationale": "Construction customer-experience case; source inspection is required before any mechanism or outcome claim is bound."},
    {"lead_id": "wave1-mv-agusta", "company": "MV Agusta", "provisional_subvertical_id": "b2b.industrial_climate.manufacturing", "provisional_company_scale": "mid_market", "source_url": "https://www.hubspot.com/case-studies/mv-agusta", "source_class": "official_platform", "discovery_rationale": "Manufacturer case with B2B/B2C segmentation and reported sales-response outcomes; historical recency and budget classification remain unresolved."},
    {"lead_id": "wave1-blue-ink-technology", "company": "Blue Ink Technology", "provisional_subvertical_id": "b2b.industrial_climate.industrial_equipment", "provisional_company_scale": "mid_market", "source_url": "https://www.hubspot.com/case-studies/blue-ink-technology", "source_class": "official_platform", "discovery_rationale": "Commercial vehicle equipment case with lead-management motion; quantified outcome and period evidence remain unresolved."},
    {"lead_id": "wave1-suzuki-south-africa", "company": "Suzuki South Africa", "provisional_subvertical_id": "b2b.industrial_climate.manufacturing", "provisional_company_scale": "mid_market", "source_url": "https://www.hubspot.com/case-studies/suzuki", "source_class": "official_platform", "discovery_rationale": "English-market automotive case with reported traffic, sales, and market-share changes after a budget cut; historical transferability needs review."},
    {"lead_id": "wave1-middleby", "company": "The Middleby Corporation", "provisional_subvertical_id": "b2b.industrial_climate.industrial_equipment", "provisional_company_scale": "enterprise_or_mass_brand", "source_url": "https://www.hubspot.com/case-studies/middleby-corporation", "source_class": "official_platform", "discovery_rationale": "Current commercial foodservice equipment case with reported time and platform-cost reductions; growth outcome linkage remains unresolved."},
    {"lead_id": "wave1-dake", "company": "Dake Corporation", "provisional_subvertical_id": "b2b.industrial_climate.industrial_equipment", "provisional_company_scale": "unresolved", "source_url": "https://www.hubspot.com/case-studies/dake", "source_class": "official_platform", "discovery_rationale": "Century-old industrial equipment customer-service modernization case; exact outcome, period, and resource scope require inspection."},
]


def main() -> int:
    source_rows = [{"url": row["source_url"], "context_ids": [f"wave1:{row['lead_id']}"]} for row in LEADS]
    capture = capture_public_sources(source_rows, max_workers=4)
    verify_public_source_capture(capture)
    capture_path = ROOT / "evidence/v10/gtm-wave1-public-source-capture-v2.json"
    atomic_write_text(capture_path, json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    payload = compile_wave1_discovery_leads(LEADS, capture)
    verify_wave1_discovery_leads(payload)
    output = ROOT / "evidence/v10/gtm-wave1-discovery-leads-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "capture_output": str(capture_path),
        "lead_count": payload["lead_count"],
        "captured_lead_count": payload["captured_lead_count"],
        "source_capture_gap_count": payload["source_capture_gap_count"],
        "distinct_provisional_subvertical_count": payload["distinct_provisional_subvertical_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
