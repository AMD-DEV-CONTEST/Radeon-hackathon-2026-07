#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path
from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import review_packet_digest, verify_unified_review_ledger
from prooflaunch_remix.gtm_case_candidate_binding_v2 import GATES
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import REQUIRED_FIELD_BINDINGS, SIX_COST_COMPONENTS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-socially-named-review-proposal-v2.json"
def _digest(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def main():
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-socially-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "Socially"]
    if len(packets) != 1: raise SystemExit(f"expected one Socially packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "independent_financial_profile")
    primary_claims = []
    for row in primary["targeted_claim_windows"]:
        marker = row["marker"].casefold()
        field = "result_summary" if marker in {"$12-18k", "$1mm", "150,000 users"} else "budget_tier"
        primary_claims.append({"field": field, "source_url": packet["source_url"], "exact_excerpt": row["bounded_exact_excerpt"], "excerpt_sha256": row["excerpt_sha256"]})
    secondary = []
    for source in dossier["sources"]:
        if source["source_role"] == "independent_financial_profile": continue
        for row in source.get("targeted_claim_windows", []): secondary.append({"source_role": source["source_role"], "source_url": source["source_url"], "source_content_sha256": source["source_content_sha256"], "independent": source["independent"], **row})
    fields = {
        "company": "RazrTech / Socially (founder: Anshul Gupta)",
        "product": "Socially, a SaaS community-building and monetization platform with web and native mobile delivery",
        "campaign_or_motion": "2023-September 2024 slow-growth, bootstrapped product motion using subscriptions, occasional lifetime deals, custom features and enterprise on-premise deployments",
        "primary_audience": "Creators, coaches, SaaS companies, communities and businesses operating paid niche communities",
        "subvertical_ids": ["b2b.b2b_saas.horizontal_saas"],
        "company_scale": "small", "observed_start": "2023-01-01", "observed_end": "2024-09-28", "recency_bucket": "twelve_to_twenty_four_months", "quota_market": "multi_market", "lifecycle_state": "growth", "budget_tier": "capital_efficient", "outcome_type": "durable_repeat",
        "result_summary": "Public founder reporting states USD 12K-18K monthly base revenue, with a few annual enterprise on-premise deals taking annual revenue to about USD 1M; separate public updates report 150,000 users and growth from more than 200 to 275 communities. These figures are not audited, and annual enterprise revenue is not relabeled as MRR.",
        "mechanism_summary": "RazrTech used service revenue to finance product iteration, then diversified Socially monetization across subscription plans, occasional lifetime deals, custom features and enterprise deployment. Slow product iteration, founder/network distribution and multiple markets accompanied growth. This is descriptive evidence and does not prove those mechanisms caused the reported revenue.",
    }
    costs = {
        "media": "Amount unknown; no complete paid-media ledger is public, so bootstrapped is not relabeled as zero paid media.",
        "people": "USD 7,000/month team-salary snapshot reported for the episode; headcount and complete compensation scope remain incomplete.",
        "tools": "USD 500/month software subscription snapshot including Canva and Figma.",
        "creator": "Amount unknown; founder, community and content labor is not separately priced.",
        "channel": "Amount unknown; payment, lifetime-deal, marketplace, partner and enterprise-sales fees are incomplete.",
        "production": "AWS USD 2,000/month and Cloudflare USD 2,200/year are explicit infrastructure snapshots; complete product, app and creative production costs are unknown.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS): raise SystemExit("Socially proposal contract drifted")
    gate_evidence = {}
    for gate in GATES:
        if gate == "public_capture_current": gate_evidence[gate] = "evidence_ready_seven_current_public_captures"
        elif gate == "exact_company_product_motion_audience": gate_evidence[gate] = dossier["gates"]["named_company_product_motion_audience"]
        elif gate == "source_bound_budget_tier_and_six_cost_components": gate_evidence[gate] = "evidence_ready" if all(str(dossier["gates"][name]).startswith("evidence_ready") for name in ("source_bound_budget_tier", "six_cost_components")) else "blocked"
        else: gate_evidence[gate] = dossier["gates"][gate]
    payload = {"schema": "ProofLaunchGTMSociallyNamedReviewProposalV2", "company": "Socially (RazrTech)", "source_unified_review_ledger_sha256": ledger["content_sha256"], "source_admission_dossier_sha256": dossier["content_sha256"], "review_packet_id": packet["review_packet_id"], "review_packet_sha256": review_packet_digest(packet), "source_url": packet["source_url"], "field_bindings": fields, "cost_components": costs, "gate_evidence": gate_evidence, "exact_primary_claim_bindings": primary_claims, "secondary_claim_bindings": secondary, "reviewer_name": None, "reviewed_at": None, "source_inspected": False, "recommended_decision_after_inspection": "submit_for_admission_gate", "decision_notes_required": True, "observed_named_human_review_count": 0, "formal_candidate_quota_credit": 0, "automatic_promotion_allowed": False, "truth_boundary": "Prefilled proposal only. RazrTech/operator and Socially/product scope remain distinct; USD 1M annual revenue includes enterprise deployments and is not MRR; cost disclosure is partial and capital-efficient does not mean zero-budget."}
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "prepared_gate_count": sum(str(value).startswith("evidence_ready") for value in gate_evidence.values()), "primary_claim_count": len(primary_claims), "secondary_claim_count": len(secondary), "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
