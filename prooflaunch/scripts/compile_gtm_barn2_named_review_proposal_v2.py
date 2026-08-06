#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import review_packet_digest, verify_unified_review_ledger
from prooflaunch_remix.gtm_case_candidate_binding_v2 import GATES
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import REQUIRED_FIELD_BINDINGS, SIX_COST_COMPONENTS


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-barn2-named-review-proposal-v2.json"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-barn2-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "Barn2"]
    if len(packets) != 1:
        raise SystemExit(f"expected one Barn2 packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "founder_interview_2026")
    primary_claims = []
    for row in primary["targeted_claim_windows"]:
        marker = row["marker"].casefold()
        if "$1.6" in marker or "$133" in marker or "$10" in marker or "plateau" in marker:
            field = "result_summary"
        elif "claude" in marker:
            field = "budget_tier"
        else:
            field = "mechanism_summary"
        primary_claims.append({"field": field, "source_url": packet["source_url"], "exact_excerpt": row["bounded_exact_excerpt"], "excerpt_sha256": row["excerpt_sha256"]})
    secondary = []
    for source in dossier["sources"]:
        if source["source_role"] == "founder_interview_2026":
            continue
        for row in source.get("targeted_claim_windows", []):
            secondary.append({"source_role": source["source_role"], "source_url": source["source_url"], "source_content_sha256": source["source_content_sha256"], "independent": source["independent"], **row})
    fields = {
        "company": "Barn2 Media Ltd (brand: Barn2; founder and CEO: Katie Keith)",
        "product": "Portfolio of WordPress and WooCommerce plugins with a newer Shopify diversification motion",
        "campaign_or_motion": "2016–June 2026 global portfolio growth through search-led education, documentation, video, affiliates, launch outreach and product cross-sell, followed by a response to the disclosed USD 1.6M annual-revenue plateau",
        "primary_audience": "WordPress, WooCommerce and Shopify site owners, operators and developers buying workflow and commerce plugins",
        "subvertical_ids": ["b2b.developer_tools.application_development"],
        "company_scale": "small",
        "observed_start": "2016-01-01",
        "observed_end": "2026-06-09",
        "recency_bucket": "three_to_six_months",
        "quota_market": "multi_market",
        "lifecycle_state": "mature",
        "budget_tier": "capital_efficient",
        "outcome_type": "failed_or_stalled",
        "result_summary": "The founder reported approximately USD 1.6M in annual revenue after ten years of plugin growth, followed by a plateau as AI and platform conditions changed. Official reports disclose earlier sales, customer, revenue-growth, profit-growth and support-volume milestones; independent profiles reproduce company and revenue scale, but the outcome is not audited.",
        "mechanism_summary": "Barn2 built compounding search and educational assets around product-specific problems, reinforced them through documentation and video, paid affiliates, launch outreach and cross-selling across related plugins. The plateau triggered an 80/20 portfolio cut, conversion work and Shopify diversification. The case teaches both the compounding mechanism and its saturation boundary; it does not prove the new diversification will recover growth.",
    }
    costs = {
        "media": "Amount unknown; the sources discuss SEO, video, outreach and community but do not publish a complete paid-media ledger.",
        "people": "Amount unknown; 2024 discloses a 19.5-person team, an external CMO-as-a-Service provider and freelance writers.",
        "tools": "Amount unknown; WordPress/Shopify development, analytics, automation and AI tools are disclosed without a complete total.",
        "creator": "Amount unknown; a dedicated video creator, designer, marketing roles and freelance writers are explicit.",
        "channel": "Bounded historical amount: USD 21,155 paid to 486 affiliates in 2021; later affiliate and marketplace economics remain unknown.",
        "production": "Amount unknown; 2021 alone reports 119 knowledge-base articles, 77 blog posts/tutorials and extensive plugin updates, without a complete production cost.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS):
        raise SystemExit("Barn2 proposal contract drifted")
    gate_evidence = {}
    for gate in GATES:
        if gate == "public_capture_current":
            gate_evidence[gate] = "evidence_ready_seven_current_public_captures"
        elif gate == "exact_company_product_motion_audience":
            gate_evidence[gate] = dossier["gates"]["named_company_product_motion_audience"]
        elif gate == "source_bound_budget_tier_and_six_cost_components":
            gate_evidence[gate] = "evidence_ready" if all(str(dossier["gates"][name]).startswith("evidence_ready") for name in ("source_bound_budget_tier", "six_cost_components")) else "blocked"
        else:
            gate_evidence[gate] = dossier["gates"][gate]
    payload = {
        "schema": "ProofLaunchGTMBarn2NamedReviewProposalV2", "company": "Barn2",
        "source_unified_review_ledger_sha256": ledger["content_sha256"], "source_admission_dossier_sha256": dossier["content_sha256"],
        "review_packet_id": packet["review_packet_id"], "review_packet_sha256": review_packet_digest(packet), "source_url": packet["source_url"],
        "field_bindings": fields, "cost_components": costs, "gate_evidence": gate_evidence,
        "exact_primary_claim_bindings": primary_claims, "secondary_claim_bindings": secondary,
        "reviewer_name": None, "reviewed_at": None, "source_inspected": False,
        "recommended_decision_after_inspection": "submit_for_admission_gate", "decision_notes_required": True,
        "observed_named_human_review_count": 0, "formal_candidate_quota_credit": 0, "automatic_promotion_allowed": False,
        "truth_boundary": "This is a prefilled proposal, not an admitted case. Revenue and plateau are founder-stated and unaudited. The case is explicitly failed-or-stalled and capital-efficient, not zero-budget; incomplete costs remain unknown.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "prepared_gate_count": sum(str(value).startswith("evidence_ready") for value in gate_evidence.values()), "primary_claim_count": len(primary_claims), "secondary_claim_count": len(secondary), "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
