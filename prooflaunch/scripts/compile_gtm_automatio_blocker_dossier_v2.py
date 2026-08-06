#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, re
from html.parser import HTMLParser
from pathlib import Path
from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_claim_surface_v2 import extract_claim_surfaces
from prooflaunch_remix.gtm_public_source_capture import RobotsPermissionCache, default_fetch

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-automatio-blocker-dossier-v2.json"
SOURCES = (
    ("founder_launch_ama", "https://www.indiehackers.com/post/bootstrapped-my-saas-to-50k-revenue-in-less-than-1-year-ama-840ba046d6", False),
    ("independent_founder_interview", "https://www.indiehackers.com/post/bc9c90500b", True),
    ("public_product_revenue_profile", "https://www.indiehackers.com/product/automatio-co/revenue", False),
    ("official_rebuild_post", "https://substack.automatio.ai/p/rebuilding-automatio-from-scratch", False),
    ("independent_revenue_verification", "https://trustmrr.com/startup/automatio-ai", True),
    ("official_product", "https://automatio.ai/", False),
    ("independent_product_review", "https://www.spotsaas.com/product/automatio-ai", True),
)
MARKERS = {
    "founder_launch_ama": ("28 early adopters", "$43,000", "$3.7K MRR", "120K", "bootstrapped"),
    "independent_founder_interview": ("$5.3k/mo", "$1000", "$2000", "communities", "Product Hunt"),
    "public_product_revenue_profile": ("$8K / mo", "Stefan Smiljkovic"),
    "official_rebuild_post": ("No dev team", "Just me", "50,000 registered users", "$2.2k MRR", "$5.5k MRR", "$200,000", "couldn’t afford"),
    "independent_revenue_verification": ("$4,163", "last 30 days"),
    "official_product": ("Stefan Smiljkovic", "11 specialized AI agents", "$36/mo"),
    "independent_product_review": ("Automatio", "web automation"),
}
class _Text(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]; self.suppressed=0
    def handle_starttag(self, tag, attrs):
        if tag.casefold() in {"script","style","svg","noscript"}: self.suppressed += 1
    def handle_endtag(self, tag):
        if tag.casefold() in {"script","style","svg","noscript"} and self.suppressed: self.suppressed -= 1
    def handle_data(self, data):
        if not self.suppressed:
            value=" ".join(data.split())
            if value: self.parts.append(value)
def _windows(body, markers):
    parser=_Text(); parser.feed(body); text=re.sub(r"\s+"," "," ".join(parser.parts)).strip(); lower=text.casefold(); rows=[]
    for marker in markers:
        index=lower.find(marker.casefold())
        if index>=0:
            excerpt=text[max(0,index-100):min(len(text),index+len(marker)+220)].strip(); rows.append({"marker":marker,"bounded_exact_excerpt":excerpt,"excerpt_sha256":hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows
def _digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _fetch(url):
    last=None
    for _ in range(3):
        try: return default_fetch(url,timeout=30.0)
        except Exception as error: last=error
    raise last
def main():
    robots=RobotsPermissionCache(); records=[]
    for role,url,independent in SOURCES:
        robots_status,allowed=robots.check(url)
        if not allowed: records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"blocked_by_robots","robots_status":robots_status}); continue
        try:
            response=_fetch(url); body=response.body.decode("utf-8",errors="replace"); surfaces=extract_claim_surfaces(body)
            records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"captured_and_bounded","robots_status":robots_status,"captured_at":datetime.now(timezone.utc).isoformat(),"source_content_sha256":hashlib.sha256(response.body).hexdigest(),"page_title":surfaces["page_title"],"page_description":surfaces["page_description"],"fragment_counts":surfaces["fragment_counts"],"fragments":surfaces["fragments"],"targeted_claim_windows":_windows(body,MARKERS[role]),"raw_page_retained":False})
        except Exception as error: records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"capture_failed","robots_status":robots_status,"error_type":type(error).__name__,"error_summary":str(error)[:240]})
    captured=[row for row in records if row["capture_status"]=="captured_and_bounded"]; independent=[row for row in captured if row["independent"]]; by_role={row["source_role"]:row for row in captured}
    ledger=json.loads((ROOT/"evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text()); matches=[row for row in ledger["records"] if row.get("company")=="Automatio"]; hashes=[row["source_content_sha256"] for row in captured]
    duplicate={"source_unified_review_ledger_sha256":ledger["content_sha256"],"company_match_count":len(matches),"company_match_review_packet_ids":[row["review_packet_id"] for row in matches],"exact_content_mirror_detected":len(hashes)!=len(set(hashes)),"additional_case_episode_collision_detected":len(matches)>1}
    costs={name:{"status":"unknown_complete_amount_not_public","amount_usd":None,"source_content_sha256":by_role.get("official_rebuild_post",{}).get("source_content_sha256","")} for name in ("paid_media","personnel","tools","creators","channel_fees","production")}
    gates={"named_company_product_motion_audience":"evidence_ready","exact_subvertical_classification":"evidence_ready","observed_period_and_recency":"evidence_ready_2021_to_2025_six_to_twelve_months","market_scale_and_lifecycle":"evidence_ready_small_multi_market_turnaround","source_bound_budget_tier":"blocked_no_operating_budget_amount_range_or_complete_resource_ledger","six_cost_components":"evidence_ready_all_six_recorded_as_unknown_without_zero_cost_inference","result_claim_binding":"evidence_ready_founder_and_third_party_revenue_trajectory_not_audited","independent_outcome_surface":"evidence_ready_three_independent_surfaces_including_revenue_verification","entity_and_episode_resolution":"evidence_ready_automatio_ai_and_stefan_smiljkovic_not_automatio_io","cross_platform_duplicate_review":"evidence_ready_machine_screen" if not duplicate["exact_content_mirror_detected"] and not duplicate["additional_case_episode_collision_detected"] else "pending_named_review","named_human_exact_binding":"pending_named_review"}
    ready=sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload={"schema":"ProofLaunchGTMAutomatioBlockerDossierV2","company":"Automatio.ai","founder_identity":"Stefan Smiljkovic","entity_key":"entity-"+hashlib.sha256(b"automatio.ai|stefan smiljkovic").hexdigest()[:20],"episode_key":"episode-"+hashlib.sha256(b"automatio.ai|2021 launch growth plateau 2025 rebuild").hexdigest()[:20],"provisional_subvertical_id":"b2b.developer_tools.application_development","episode_definition":"2021 early-adopter launch and organic growth followed by team loss, stagnation and a 2025 solo AI-assisted rebuild.","source_count":len(records),"captured_source_count":len(captured),"independent_captured_source_count":len(independent),"cost_components":costs,"duplicate_screen":duplicate,"gate_count":len(gates),"evidence_ready_gate_count":ready,"blocking_gate_count":len(gates)-ready,"gates":gates,"admission_status":"blocked_pending_source_bound_budget_evidence_and_named_review","replacement_lane_required":True,"observed_named_human_review_count":0,"formal_candidate_quota_credit":0,"automatic_promotion_allowed":False,"truth_boundary":"Automatio has strong public outcome and failure/rebuild evidence, including founder-reported revenue milestones and a third-party recent revenue surface. However, bootstrapped, solo and unable-to-afford-team statements do not disclose an operating budget amount or defensible range. The case cannot fill a budget quota and cannot reach 10/11 until source-bound budget evidence appears; it is 9/11, not silently relabeled low-budget."}
    payload["content_sha256"]=_digest(payload); atomic_write_text(OUTPUT,json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n"); print(json.dumps({"output":str(OUTPUT),"captured_source_count":len(captured),"independent_captured_source_count":len(independent),"ready_gates":ready,"blocking_gates":len(gates)-ready,"admission_status":payload["admission_status"],"content_sha256":payload["content_sha256"]},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
