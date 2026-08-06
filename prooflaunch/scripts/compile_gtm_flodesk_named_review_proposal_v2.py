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
OUTPUT = ROOT / "evidence/v10/gtm-flodesk-named-review-proposal-v2.json"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-flodesk-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "Flodesk"]
    if len(packets) != 1:
        raise SystemExit(f"expected one Flodesk packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "founder_interview")
    primary_claims = []
    for row in primary["targeted_claim_windows"]:
        marker = row["marker"].casefold()
        if "$90k" in marker:
            field = "budget_tier"
        elif "$36" in marker or "four months" in marker:
            field = "result_summary"
        else:
            field = "mechanism_summary"
        primary_claims.append({
            "field": field,
            "source_url": packet["source_url"],
            "exact_excerpt": row["bounded_exact_excerpt"],
            "excerpt_sha256": row["excerpt_sha256"],
        })
    secondary = []
    for source in dossier["sources"]:
        if source["source_role"] == "founder_interview":
            continue
        for row in source.get("targeted_claim_windows", []):
            secondary.append({
                "source_role": source["source_role"],
                "source_url": source["source_url"],
                "source_content_sha256": source["source_content_sha256"],
                "independent": source["independent"],
                **row,
            })
    fields = {
        "company": "Flodesk (Flodesk, Inc.)",
        "product": "Design-led email marketing, automation, forms, checkout and AI email design platform",
        "campaign_or_motion": "2019–2026 bootstrapped product-led and viral-loop growth from launch to more than $36M ARR, using a branded email footer, word of mouth, design differentiation and simple pricing",
        "primary_audience": "Small businesses, creators and solopreneurs that treat email as a branded customer touchpoint",
        "subvertical_ids": ["b2b.martech_sales_tech.marketing_automation"],
        "company_scale": "mid_market",
        "observed_start": "2019-01-01",
        "observed_end": "2026-04-22",
        "recency_bucket": "three_to_six_months",
        "quota_market": "multi_market",
        "lifecycle_state": "growth",
        "budget_tier": "capital_efficient",
        "outcome_type": "durable_repeat",
        "result_summary": "Founder reporting records approximately $90K pooled savings, profitability within two weeks, $1M ARR within four months, more than $36M ARR and 100,000+ paying customers; independent AWS and Practical Founders surfaces corroborate earlier scale milestones.",
        "mechanism_summary": "The reported sequence combines design-first differentiation, a branded-footer viral loop, word of mouth, a performance model and initially non-tiered pricing. It is a descriptive multi-mechanism episode, not proof that any single tactic caused the outcome.",
    }
    costs = {
        "media": "Amount unknown; the founder reports organic and word-of-mouth growth but does not prove paid media was zero.",
        "people": "Amount unknown; sources disclose approximately 35 employees at an earlier milestone and roughly 90 later, but no complete personnel cost.",
        "tools": "Amount unknown; product and infrastructure scope is visible, but no source-bound tool total is disclosed.",
        "creator": "Amount unknown; founder-led design and brand work are described without isolated creator labor cost.",
        "channel": "Amount unknown; global email distribution and payment surfaces are described without the company's channel-fee total.",
        "production": "Amount unknown; design and engineering production scope is described without a complete production amount.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS):
        raise SystemExit("Flodesk proposal contract drifted")
    gate_evidence = {}
    for gate in GATES:
        if gate == "public_capture_current":
            gate_evidence[gate] = "evidence_ready_seven_current_public_captures"
        elif gate == "exact_company_product_motion_audience":
            gate_evidence[gate] = dossier["gates"]["named_company_product_motion_audience"]
        elif gate == "source_bound_budget_tier_and_six_cost_components":
            gate_evidence[gate] = "evidence_ready" if all(
                str(dossier["gates"][name]).startswith("evidence_ready")
                for name in ("source_bound_budget_tier", "six_cost_components")
            ) else "blocked"
        else:
            gate_evidence[gate] = dossier["gates"][gate]
    payload = {
        "schema": "ProofLaunchGTMFlodeskNamedReviewProposalV2",
        "company": "Flodesk",
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "source_admission_dossier_sha256": dossier["content_sha256"],
        "review_packet_id": packet["review_packet_id"],
        "review_packet_sha256": review_packet_digest(packet),
        "source_url": packet["source_url"],
        "field_bindings": fields,
        "cost_components": costs,
        "gate_evidence": gate_evidence,
        "exact_primary_claim_bindings": primary_claims,
        "secondary_claim_bindings": secondary,
        "reviewer_name": None,
        "reviewed_at": None,
        "source_inspected": False,
        "recommended_decision_after_inspection": "submit_for_admission_gate",
        "decision_notes_required": True,
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "truth_boundary": "This is a prefilled proposal, not a review or admitted candidate. The $90K savings figure bounds the initial resource pool; it does not prove zero paid media, complete spend, or single-mechanism causality.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "prepared_gate_count": sum(str(value).startswith("evidence_ready") for value in gate_evidence.values()),
        "primary_claim_count": len(primary_claims),
        "secondary_claim_count": len(secondary),
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
