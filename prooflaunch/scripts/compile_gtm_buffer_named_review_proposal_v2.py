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
OUTPUT = ROOT / "evidence/v10/gtm-buffer-named-review-proposal-v2.json"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-buffer-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "Buffer"]
    if len(packets) != 1:
        raise SystemExit(f"expected one Buffer packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "company_growth_postmortem")
    primary_claims = []
    for row in primary["targeted_claim_windows"]:
        marker = row["marker"].casefold()
        if "million" in marker or "registered" in marker or "team" in marker:
            field = "result_summary"
        elif "strategy" in marker or "content" in marker:
            field = "mechanism_summary"
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
        if source["source_role"] == "company_growth_postmortem":
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
        "company": "Buffer (Buffer, Inc.)",
        "product": "Social media publishing, scheduling, analytics and engagement platform",
        "campaign_or_motion": "2010–2016 content-led compound growth from initial launch to $10M ARR, reinforced by customer research, pricing, product expansion, data discipline and company transparency",
        "primary_audience": "Small businesses, creators and marketing teams that need repeatable organic social publishing and audience growth",
        "subvertical_ids": ["b2b.martech_sales_tech.marketing_automation"],
        "company_scale": "mid_market",
        "observed_start": "2010-11-01",
        "observed_end": "2016-06-02",
        "recency_bucket": "historical_mechanism",
        "quota_market": "multi_market",
        "lifecycle_state": "growth",
        "budget_tier": "mature_scale",
        "outcome_type": "durable_repeat",
        "result_summary": "Company reporting records $10M ARR, 3M registered users and 90+ team members by June 2016; independent TechCrunch reporting confirms the earlier rise from approximately $2.143M to $4.832M annual run rate.",
        "mechanism_summary": "Buffer reports focusing on content marketing as the first-year primary channel, then adding customer research, disciplined experiments, pricing changes, product expansion and transparent company reporting. This is a descriptive compound-growth episode, not proof that content alone caused the result.",
    }
    costs = {
        "media": "Disclosed monthly: $6,302.40 advertising and marketing in the company transparent-pricing ledger.",
        "people": "Disclosed monthly: $223,939.74 team salaries; the source separately describes functional allocation.",
        "tools": "Disclosed monthly: $14,161.79 for tools; servers were separately $22,890.76.",
        "creator": "Amount unknown; the growth postmortem identifies content marketing and a 90+ person organization but does not isolate creator labor from salaries.",
        "channel": "Disclosed monthly: $13,885.42 in Stripe fees, retained as the episode's bounded channel/payment fee component.",
        "production": "Bounded monthly: $2,577.81 computer and equipment; the source does not disclose a complete content-production total.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS):
        raise SystemExit("Buffer proposal contract drifted")
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
        "schema": "ProofLaunchGTMBufferNamedReviewProposalV2",
        "company": "Buffer",
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
        "truth_boundary": "This prefilled proposal preserves the source language and machine gate state. It is not a review, causal proof or admitted candidate; a named reviewer must inspect all seven sources and confirm the cost and episode meanings.",
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
