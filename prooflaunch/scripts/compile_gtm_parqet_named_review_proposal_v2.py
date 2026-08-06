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
OUTPUT = ROOT / "evidence/v10/gtm-parqet-named-review-proposal-v2.json"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    dossier = json.loads((ROOT / "evidence/v10/gtm-parqet-admission-dossier-v2.json").read_text())
    verify_unified_review_ledger(ledger)
    packets = [row for row in ledger["records"] if row.get("company") == "Parqet"]
    if len(packets) != 1:
        raise SystemExit(f"expected one Parqet packet, observed {len(packets)}")
    packet = packets[0]
    primary = next(row for row in dossier["sources"] if row["source_role"] == "founder_interview_2024")
    primary_claims = []
    for row in primary["targeted_claim_windows"]:
        marker = row["marker"].casefold()
        if "$100" in marker or "first five" in marker or "paid ads" in marker or "revenue cut" in marker:
            field = "budget_tier"
        elif "$108" in marker or "€100" in marker or "€20" in marker:
            field = "result_summary"
        else:
            field = "mechanism_summary"
        primary_claims.append({"field": field, "source_url": packet["source_url"], "exact_excerpt": row["bounded_exact_excerpt"], "excerpt_sha256": row["excerpt_sha256"]})
    secondary = []
    for source in dossier["sources"]:
        if source["source_role"] == "founder_interview_2024":
            continue
        for row in source.get("targeted_claim_windows", []):
            secondary.append({"source_role": source["source_role"], "source_url": source["source_url"], "source_content_sha256": source["source_content_sha256"], "independent": source["independent"], **row})
    fields = {
        "company": "Parqet Fintech GmbH (product: Parqet; founder and managing director: Sumit Kumar)",
        "product": "Freemium portfolio-tracking web and mobile software for retail investors",
        "campaign_or_motion": "December 2019–August 2024 DACH-first product-led growth: hyper-local product scope, public portfolio sharing, word of mouth, community trust, Reddit and livestreams, followed by YouTube, programmatic SEO, affiliate revenue share and paid acquisition",
        "primary_audience": "Retail investors in Germany, Austria and Switzerland managing stocks, ETFs, crypto and other assets across brokers",
        "subvertical_ids": ["b2c.personal_finance.investing"],
        "company_scale": "small",
        "observed_start": "2019-12-01",
        "observed_end": "2024-08-02",
        "recency_bucket": "historical_mechanism",
        "quota_market": "multi_market",
        "lifecycle_state": "growth",
        "budget_tier": "low_budget",
        "outcome_type": "durable_repeat",
        "result_summary": "The founder reported approximately €100K MRR in August 2024 after earlier public milestones of 17K+ MRR and about 100,000 registered users in 2021. Independent pages reproduce the trajectory and explicitly label the latest revenue as founder-stated and unaudited.",
        "mechanism_summary": "The observed motion began with a founder-use problem and extremely narrow DACH localization, embedded public portfolio sharing as a distribution loop, added community trust through livestreams, and later diversified into SEO, YouTube, affiliate partnerships and paid ads. The sequence is descriptive, not proof that any single channel caused the result.",
    }
    costs = {
        "media": "Complete amount unknown; the first two years are described as organic, while the later episode explicitly includes paid ads.",
        "people": "Amount unknown; founder labor was intensive, the founder was employee five around €20K MRR, and later team costs are not fully disclosed.",
        "tools": "Bounded early operating spend: about USD 100 per month for the first five months, retained conservatively as USD 500 total for that window; later data and infrastructure costs remain unknown.",
        "creator": "Amount unknown; founder livestream/YouTube labor and influencer affiliate revenue share are disclosed without a complete total.",
        "channel": "Amount unknown; affiliate commissions, payment processing and other channel fees are not fully disclosed.",
        "production": "Amount unknown; extensive evening/weekend founder build and content labor is explicit and is not treated as free.",
    }
    if set(fields) != set(REQUIRED_FIELD_BINDINGS) or set(costs) != set(SIX_COST_COMPONENTS):
        raise SystemExit("Parqet proposal contract drifted")
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
        "schema": "ProofLaunchGTMParqetNamedReviewProposalV2",
        "company": "Parqet",
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
        "truth_boundary": "This is a prefilled proposal, not a review or admitted case. Revenue remains founder-stated; later paid media, team, affiliate, data and production totals remain unknown.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "prepared_gate_count": sum(str(value).startswith("evidence_ready") for value in gate_evidence.values()), "primary_claim_count": len(primary_claims), "secondary_claim_count": len(secondary), "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
