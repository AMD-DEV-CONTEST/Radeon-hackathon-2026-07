#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import review_packet_digest,verify_unified_review_ledger
from prooflaunch_remix.gtm_case_candidate_binding_v2 import GATES
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import REQUIRED_FIELD_BINDINGS,SIX_COST_COMPONENTS

ROOT=Path(__file__).resolve().parents[1]; OUTPUT=ROOT/"evidence/v10/gtm-rightmessage-named-review-proposal-v2.json"
def _digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main():
    ledger=json.loads((ROOT/"evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text()); dossier=json.loads((ROOT/"evidence/v10/gtm-rightmessage-admission-dossier-v2.json").read_text()); verify_unified_review_ledger(ledger)
    packets=[row for row in ledger["records"] if row.get("company")=="RightMessage"]
    if len(packets)!=1: raise SystemExit(f"expected one RightMessage packet, observed {len(packets)}")
    packet=packets[0]; primary=next(row for row in dossier["sources"] if row["source_role"]=="founder_interview_2026"); primary_claims=[]
    for row in primary["targeted_claim_windows"]:
        marker=row["marker"].casefold(); field="result_summary" if "$30" in marker or "roughly" in marker else "budget_tier" if marker in {"cofounder","money in the bank","team"} else "mechanism_summary"
        primary_claims.append({"field":field,"source_url":packet["source_url"],"exact_excerpt":row["bounded_exact_excerpt"],"excerpt_sha256":row["excerpt_sha256"]})
    secondary=[]
    for source in dossier["sources"]:
        if source["source_role"]=="founder_interview_2026": continue
        for row in source.get("targeted_claim_windows",[]): secondary.append({"source_role":source["source_role"],"source_url":source["source_url"],"source_content_sha256":source["source_content_sha256"],"independent":source["independent"],**row})
    fields={"company":"RightMessage, Inc. (founders: Brennan Dunn and Shai Schechter)","product":"Website and email audience segmentation, personalization and conversion software","campaign_or_motion":"2017–April 2026 launch, audience-led annual-prepay acquisition, funded team expansion, plateau and near-bankruptcy, followed by solo-led product rebuild and renewed founder-stated USD 30K MRR","primary_audience":"Creators, educators, SaaS and online businesses using email platforms and websites to segment audiences and improve conversion","subvertical_ids":["b2b.martech_sales_tech.marketing_automation"],"company_scale":"small","observed_start":"2017-01-01","observed_end":"2026-04-03","recency_bucket":"three_to_six_months","quota_market":"multi_market","lifecycle_state":"growth","budget_tier":"mixed_budget","outcome_type":"turnaround","result_summary":"The current founder reports roughly USD 30K MRR about one year after a rebuild. Earlier founder/independent records document the original USD 30K MRR launch, a funded ten-person expansion, plateau and near-bankruptcy. Claims are not audited and the two USD 30K periods are distinct milestones inside one long turnaround episode, not duplicate quota credits.","mechanism_summary":"The original motion converted an existing audience through build-in-public email, guest posts, podcasts, speaking and annual prepay with concierge setup. Scaling capital and team complexity did not prevent plateau and near-bankruptcy. The rebuild narrowed ownership and product scope, retained founder-market knowledge and reintroduced growth. This is descriptive turnaround evidence, not proof that founder-led rebuilding causes recovery."}
    costs={"media":"Amount unknown; content, guest posting, podcasting, speaking and email are explicit, but complete paid media is not disclosed.","people":"Amount unknown; a historical ten-person team and current solo-founder labor are explicit, while compensation is not itemized.","tools":"Amount unknown; product, email, data, compliance and AI/MCP infrastructure costs are incomplete.","creator":"Amount unknown; founder content, guest posts, podcasts, speaking and launch-email production are not separately priced.","channel":"Amount unknown; payment, affiliate, ESP/CRM integration and partner economics are incomplete.","production":"Amount unknown; original build, concierge onboarding, near-bankruptcy transition and full rebuild are not separately costed. Historical total operating expense was estimated at about USD 20K/month but is not falsely allocated among components."}
    if set(fields)!=set(REQUIRED_FIELD_BINDINGS) or set(costs)!=set(SIX_COST_COMPONENTS): raise SystemExit("RightMessage proposal contract drifted")
    gate_evidence={}
    for gate in GATES:
        if gate=="public_capture_current": gate_evidence[gate]="evidence_ready_seven_current_public_captures"
        elif gate=="exact_company_product_motion_audience": gate_evidence[gate]=dossier["gates"]["named_company_product_motion_audience"]
        elif gate=="source_bound_budget_tier_and_six_cost_components": gate_evidence[gate]="evidence_ready" if all(str(dossier["gates"][name]).startswith("evidence_ready") for name in ("source_bound_budget_tier","six_cost_components")) else "blocked"
        else: gate_evidence[gate]=dossier["gates"][gate]
    payload={"schema":"ProofLaunchGTMRightMessageNamedReviewProposalV2","company":"RightMessage","source_unified_review_ledger_sha256":ledger["content_sha256"],"source_admission_dossier_sha256":dossier["content_sha256"],"review_packet_id":packet["review_packet_id"],"review_packet_sha256":review_packet_digest(packet),"source_url":packet["source_url"],"field_bindings":fields,"cost_components":costs,"gate_evidence":gate_evidence,"exact_primary_claim_bindings":primary_claims,"secondary_claim_bindings":secondary,"reviewer_name":None,"reviewed_at":None,"source_inspected":False,"recommended_decision_after_inspection":"submit_for_admission_gate","decision_notes_required":True,"observed_named_human_review_count":0,"formal_candidate_quota_credit":0,"automatic_promotion_allowed":False,"truth_boundary":"Prefilled proposal only. The USD 30K MRR turnaround is founder-stated, capital records conflict between USD 500K and USD 700K, historical USD 20K monthly total expense is not componentized, and no causality or zero-budget claim is allowed."}
    payload["content_sha256"]=_digest(payload); atomic_write_text(OUTPUT,json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n"); print(json.dumps({"output":str(OUTPUT),"prepared_gate_count":sum(str(value).startswith("evidence_ready") for value in gate_evidence.values()),"primary_claim_count":len(primary_claims),"secondary_claim_count":len(secondary),"content_sha256":payload["content_sha256"]},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
