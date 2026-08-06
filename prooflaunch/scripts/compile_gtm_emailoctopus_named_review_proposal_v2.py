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
OUTPUT = ROOT / "evidence/v10/gtm-emailoctopus-named-review-proposal-v2.json"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-emailoctopus-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "EmailOctopus"]
    if len(packets) != 1:
        raise SystemExit(f"expected one EmailOctopus packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "company_marketing_postmortem")
    primary_claims = primary["targeted_claim_windows"]
    exact_claim_bindings = [{
        "field": "result_summary" if "$3m" in row["marker"].casefold() else "budget_tier",
        "source_url": packet["source_url"],
        "exact_excerpt": row["bounded_exact_excerpt"],
        "excerpt_sha256": row["excerpt_sha256"],
    } for row in primary_claims]
    secondary_claims = []
    for source in dossier["sources"]:
        if source["source_role"] == "company_marketing_postmortem":
            continue
        for row in source.get("targeted_claim_windows", []):
            secondary_claims.append({
                "source_role": source["source_role"],
                "source_url": source["source_url"],
                "source_content_sha256": source["source_content_sha256"],
                "independent": source["source_role"] in {"independent_founder_profile", "independent_accounting_partner_case", "official_company_registry"},
                **row,
            })
    fields = {
        "company": "EmailOctopus (Three Hearts Digital Ltd, UK company 09897211)",
        "product": "Global email marketing platform for cost-sensitive small businesses, creators, authors and organizations",
        "campaign_or_motion": "2014–2023 bootstrapped compound-growth motion combining free launch, Reddit/community, SEO/content, paid search, affiliates and selective sponsorships",
        "primary_audience": "Small businesses and independent operators with meaningful email lists and high price sensitivity",
        "subvertical_ids": ["b2b.martech_sales_tech.marketing_automation"],
        "company_scale": "small",
        "observed_start": "2014-01-01",
        "observed_end": "2023-07-18",
        "recency_bucket": "historical_mechanism",
        "quota_market": "multi_market",
        "lifecycle_state": "growth",
        "budget_tier": "mature_scale",
        "outcome_type": "durable_repeat",
        "result_summary": "Company source reports more than $3M ARR; independent surfaces report $130K MRR at an earlier stage, operations across 119 countries, 92,000+ organizations and 43B+ emails.",
        "mechanism_summary": "A sequenced portfolio moved from low-risk community and product-led distribution into SEO/content, paid search, affiliates and selective sponsorships; no single-channel causal claim is asserted.",
    }
    costs = {
        "media": "Disclosed: approximately $15,000/month Google Ads; two Indie Hackers newsletter positions cost $1,000.",
        "people": "Amount unknown; two founders were full-time for four years by 2021 and the remote team had nine people, later independently reported as fifteen.",
        "tools": "Amount partially bounded; founder reporting says hosting scaled at about 10% of revenue during the early period.",
        "creator": "Amount unknown; company history reports up to five freelancers across technical, design and content roles.",
        "channel": "Disclosed: under $3,500/month affiliates and £275 × 50 podcast episodes; two affiliates drove 90% of referred revenue.",
        "production": "Amount unknown; initial domain purchase and Fiverr-produced logo are explicitly disclosed and are not treated as free.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS):
        raise SystemExit("proposal field or cost contract drifted")
    gate_evidence = {}
    for gate in GATES:
        if gate == "public_capture_current":
            gate_evidence[gate] = "evidence_ready_seven_current_public_captures"
        elif gate == "source_bound_budget_tier_and_six_cost_components":
            budget_ready = str(dossier["gates"]["source_bound_budget_tier"]).startswith("evidence_ready")
            costs_ready = str(dossier["gates"]["six_cost_components"]).startswith("evidence_ready")
            gate_evidence[gate] = "evidence_ready" if budget_ready and costs_ready else "blocked"
        elif gate == "exact_company_product_motion_audience":
            gate_evidence[gate] = dossier["gates"]["named_company_product_motion_audience"]
        else:
            gate_evidence[gate] = dossier["gates"][gate]
    payload = {
        "schema": "ProofLaunchGTMEmailOctopusNamedReviewProposalV2",
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "source_admission_dossier_sha256": dossier["content_sha256"],
        "review_packet_id": packet["review_packet_id"],
        "review_packet_sha256": review_packet_digest(packet),
        "source_url": packet["source_url"],
        "field_bindings": fields,
        "cost_components": costs,
        "gate_evidence": gate_evidence,
        "exact_primary_claim_bindings": exact_claim_bindings,
        "secondary_claim_bindings": secondary_claims,
        "reviewer_name": None,
        "reviewed_at": None,
        "source_inspected": False,
        "recommended_decision_after_inspection": "submit_for_admission_gate",
        "decision_notes_required": True,
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "operator_instructions": [
            "Open and inspect every bound source; compare the exact excerpts to the full context.",
            "Confirm the legal entity, episode boundary, budget tier, unknown cost amounts and descriptive-not-causal result wording.",
            "Enter reviewer name, UTC timestamp, source_inspected=true and a written decision in the unified workbench.",
            "Only after the named intake validator passes may the separate CaseCandidateV2 admission compiler issue quota credit.",
        ],
        "truth_boundary": "This is a prefilled proposal, not a human review and not a candidate. Ten evidence gates are prepared; the named-human gate is deliberately false and cannot be completed by this compiler.",
    }
    payload["content_sha256"] = digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "prepared_gate_count": sum(str(v).startswith("evidence_ready") for v in gate_evidence.values()), "primary_claim_count": len(exact_claim_bindings), "secondary_claim_count": len(secondary_claims), "formal_candidate_quota_credit": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
