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
OUTPUT = ROOT / "evidence/v10/gtm-postbridge-named-review-proposal-v2.json"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-postbridge-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "Post Bridge"]
    if len(packets) != 1:
        raise SystemExit(f"expected one Post Bridge packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "founder_interview")
    primary_claims = []
    for row in primary["targeted_claim_windows"]:
        marker = row["marker"].casefold()
        if "nothing except time" in marker or "$100" in marker or "$1,000" in marker:
            field = "budget_tier"
        elif "$35" in marker or "eight months" in marker or "six months" in marker:
            field = "result_summary"
        else:
            field = "mechanism_summary"
        primary_claims.append({"field": field, "source_url": packet["source_url"], "exact_excerpt": row["bounded_exact_excerpt"], "excerpt_sha256": row["excerpt_sha256"]})
    secondary = []
    for source in dossier["sources"]:
        if source["source_role"] == "founder_interview":
            continue
        for row in source.get("targeted_claim_windows", []):
            secondary.append({"source_role": source["source_role"], "source_url": source["source_url"], "source_content_sha256": source["source_content_sha256"], "independent": source["independent"], **row})
    fields = {
        "company": "Post Bridge (founder/product identity: Jack Friks; legal entity not publicly bound)",
        "product": "Multi-platform social media publishing and scheduling software for creators and small teams",
        "campaign_or_motion": "October 2024–June 2026 solo-founder product-led and content-led growth using self-use validation, X build-in-public distribution, repeated short-form formats, hard-paywall pricing and rapid product iteration",
        "primary_audience": "Creators, solo founders and small teams that need to publish platform-native content across multiple social networks",
        "subvertical_ids": ["b2b.martech_sales_tech.marketing_automation"],
        "company_scale": "small",
        "observed_start": "2024-10-01",
        "observed_end": "2026-06-17",
        "recency_bucket": "three_to_six_months",
        "quota_market": "multi_market",
        "lifecycle_state": "growth",
        "budget_tier": "low_budget",
        "outcome_type": "recent_breakout",
        "result_summary": "The founder reports $35K MRR after an eight-month plateau followed by doubling over six months. Independent pages reproduce the founder-stated result, one historical page records $11K MRR, and a public dashboard surface reports a later estimate; none is treated as an audited filing.",
        "mechanism_summary": "The described motion starts with the founder's own cross-posting problem, validates demand through public sharing, compounds through X and short-form content, reuses winning formats with variation, prices behind a hard paywall, and keeps the product and operating stack narrow. This is descriptive, not causal proof.",
    }
    costs = {
        "media": "Amount unknown; content-led growth is reported, but the episode does not prove all paid media was zero.",
        "people": "Amount unknown; founder labor and occasional contractor work are disclosed but not priced.",
        "tools": "Bounded current infrastructure: $100–200/month; a prior Supabase egress configuration reached about $1,000/month before migration.",
        "creator": "Amount unknown; the founder produced repeated X and short-form content without an isolated labor amount.",
        "channel": "Amount unknown; official platform APIs and billing are visible, but company-side API/payment fees are not disclosed.",
        "production": "Economic amount unknown; the founder reports zero initial cash build cost but explicitly contributed time, which is not treated as free labor.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS):
        raise SystemExit("Post Bridge proposal contract drifted")
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
        "schema": "ProofLaunchGTMPostBridgeNamedReviewProposalV2",
        "company": "Post Bridge",
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
        "truth_boundary": "This is a prefilled proposal, not a review or admitted case. Founder time and contractor labor remain unknown; public revenue is founder-stated/estimated rather than audited.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "prepared_gate_count": sum(str(value).startswith("evidence_ready") for value in gate_evidence.values()), "primary_claim_count": len(primary_claims), "secondary_claim_count": len(secondary), "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
