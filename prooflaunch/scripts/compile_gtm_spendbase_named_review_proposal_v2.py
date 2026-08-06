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
OUTPUT = ROOT / "evidence/v10/gtm-spendbase-named-review-proposal-v2.json"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-spendbase-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "Spendbase"]
    if len(packets) != 1:
        raise SystemExit(f"expected one Spendbase packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "founder_interview_2026")
    primary_claims = []
    for row in primary["targeted_claim_windows"]:
        marker = row["marker"].casefold()
        if "arr" in marker or "yoy" in marker or "800" in marker:
            field = "result_summary"
        elif "200" in marker or "bootstrapped" in marker:
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
        "company": "Spendbase, Inc. (product: Spendbase; cofounder: Andrew Alex)",
        "product": "B2B spend-management platform spanning SaaS and cloud optimization, procurement, vendor negotiation, banking and corporate cards",
        "campaign_or_motion": "2023–April 2026 global savings-led growth using measurable customer ROI, savings-based pricing, referrals, finance-consultancy and VC/technology-ecosystem partnerships, followed by multi-product expansion",
        "primary_audience": "Finance, procurement and operations leaders at technology-enabled businesses with recurring SaaS, cloud and corporate spending",
        "subvertical_ids": ["b2b.b2b_saas.finance_operations"],
        "company_scale": "enterprise_or_mass_brand",
        "observed_start": "2023-01-01",
        "observed_end": "2026-04-02",
        "recency_bucket": "three_to_six_months",
        "quota_market": "multi_market",
        "lifecycle_state": "mature",
        "budget_tier": "mature_scale",
        "outcome_type": "mature_control",
        "result_summary": "The founder reported eight-figure ARR, 300% year-over-year growth and more than 800 business customers by April 2026. Independent sources corroborate company scale and disclosed capital, but the revenue claim is not audited.",
        "mechanism_summary": "Spendbase framed pricing around verified savings, turning customer ROI into referral and partner proof, used finance consultancies, venture and technology ecosystems as distribution, then expanded from SaaS/cloud optimization into banking and cards. The evidence is descriptive and does not prove that any single channel caused the outcome.",
    }
    costs = {
        "media": "Amount unknown; no complete paid-media ledger is public, so organic and partnership language is not converted into a zero-spend claim.",
        "people": "Amount unknown; official and founder pages disclose roughly 180–200+ headcount across regions, which is retained as mature-scale resource evidence rather than free labor.",
        "tools": "Amount unknown; SaaS, cloud, compliance, analytics, data and internal operating-stack costs are not fully disclosed.",
        "creator": "Amount unknown; executive thought-leadership, content and partner-marketing labor are not separately priced.",
        "channel": "Amount unknown; partner, banking, card, payment, accelerator and ecosystem fees or economics are incomplete.",
        "production": "Amount unknown; product, research, content, event and sales-production costs are not fully disclosed.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS):
        raise SystemExit("Spendbase proposal contract drifted")
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
        "schema": "ProofLaunchGTMSpendbaseNamedReviewProposalV2",
        "company": "Spendbase",
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
        "truth_boundary": "This is a prefilled proposal, not an admitted case. Revenue is founder-stated and unaudited; exact media, people, tool, creator, channel and production totals remain unknown. The case is mature-scale, not zero-budget.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "prepared_gate_count": sum(str(value).startswith("evidence_ready") for value in gate_evidence.values()), "primary_claim_count": len(primary_claims), "secondary_claim_count": len(secondary), "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
