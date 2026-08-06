#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_claim_surface_v2 import extract_claim_surfaces
from prooflaunch_remix.gtm_public_source_capture import RobotsPermissionCache, default_fetch

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-rightmessage-admission-dossier-v2.json"
SOURCES = (
    ("founder_interview_2026", "https://www.indiehackers.com/post/tech/building-failing-rebuilding-and-then-hitting-30k-mrr-in-a-year-JpcXzLO5sk8IEHz50bPO", False),
    ("independent_launch_profile", "https://www.starterstory.com/stories/how-we-grew-our-saas-to-30k-mrr-in-one-year", True),
    ("independent_financial_interview", "https://getlatka.com/companies/rightmessage/customers", True),
    ("cofounder_exit_account", "https://shai.io/rightmessage-exit/", False),
    ("official_pricing", "https://rightmessage.com/pricing", False),
    ("independent_growth_reconstruction", "https://growthpartners.online/stories/how-rightmessage-went-from-0-to-30k-mrr", True),
    ("independent_company_profile", "https://ooutliers.com/startups/rightmessage", True),
)
MARKERS = {
    "founder_interview_2026": ("$30k MRR", "roughly a year", "solo founder", "cofounder", "money in the bank", "team", "rebuilding"),
    "independent_launch_profile": ("1,000 websites", "$30k/mo", "January 2018", "limited beta"),
    "independent_financial_interview": ("half a million", "expenses are probably 20k", "10k a month profit", "2,000", "8k", "300"),
    "cofounder_exit_account": ("$75k-revenue", "$700k investment", "10-person team", "almost bankruptcy", "millions in revenue"),
    "official_pricing": ("Save 20%", "30-day money-back", "14-day trial", "SOC2"),
    "independent_growth_reconstruction": ("$30K MRR", "12 months"),
    "independent_company_profile": ("1,000 websites", "$30K MRR", "within a year"),
}

class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True); self.parts=[]; self.suppressed=0
    def handle_starttag(self, tag, attrs):
        if tag.casefold() in {"script","style","svg","noscript"}: self.suppressed += 1
    def handle_endtag(self, tag):
        if tag.casefold() in {"script","style","svg","noscript"} and self.suppressed: self.suppressed -= 1
    def handle_data(self, data):
        if not self.suppressed:
            value=" ".join(data.split())
            if value: self.parts.append(value)

def _windows(body: str, markers: tuple[str, ...]) -> list[dict[str,str]]:
    parser=_Text(); parser.feed(body); text=re.sub(r"\s+"," "," ".join(parser.parts)).strip(); lower=text.casefold(); rows=[]
    for marker in markers:
        index=lower.find(marker.casefold())
        if index >= 0:
            excerpt=text[max(0,index-100):min(len(text),index+len(marker)+220)].strip()
            rows.append({"marker":marker,"bounded_exact_excerpt":excerpt,"excerpt_sha256":hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows

def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _fetch(url: str):
    last=None
    for _ in range(3):
        try: return default_fetch(url,timeout=30.0)
        except Exception as error: last=error
    raise last

def main() -> int:
    robots=RobotsPermissionCache(); records=[]
    for role,url,independent in SOURCES:
        robots_status,allowed=robots.check(url)
        if not allowed:
            records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"blocked_by_robots","robots_status":robots_status}); continue
        try:
            response=_fetch(url); body=response.body.decode("utf-8",errors="replace"); surfaces=extract_claim_surfaces(body)
            records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"captured_and_bounded","robots_status":robots_status,"captured_at":datetime.now(timezone.utc).isoformat(),"source_content_sha256":hashlib.sha256(response.body).hexdigest(),"page_title":surfaces["page_title"],"page_description":surfaces["page_description"],"fragment_counts":surfaces["fragment_counts"],"fragments":surfaces["fragments"],"targeted_claim_windows":_windows(body,MARKERS.get(role,())),"raw_page_retained":False})
        except Exception as error:
            records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"capture_failed","robots_status":robots_status,"error_type":type(error).__name__,"error_summary":str(error)[:240]})
    captured=[row for row in records if row["capture_status"]=="captured_and_bounded"]; by_role={row["source_role"]:row for row in captured}; independent=[row for row in captured if row["independent"]]
    primary_hash=by_role.get("founder_interview_2026",{}).get("source_content_sha256",""); financial_hash=by_role.get("independent_financial_interview",{}).get("source_content_sha256",""); exit_hash=by_role.get("cofounder_exit_account",{}).get("source_content_sha256","")
    costs={
        "paid_media":{"status":"unknown_complete_paid_media_ledger_not_public","amount_usd":None,"source_content_sha256":primary_hash},
        "personnel":{"status":"unknown_historical_ten_person_team_and_current_solo_labor","amount_usd":None,"source_content_sha256":exit_hash or primary_hash},
        "tools":{"status":"unknown_product_email_data_and_ai_stack","amount_usd":None,"source_content_sha256":primary_hash},
        "creators":{"status":"unknown_founder_content_guest_posting_podcast_and_event_labor","amount_usd":None,"source_content_sha256":financial_hash or primary_hash},
        "channel_fees":{"status":"unknown_payment_affiliate_and_integration_economics","amount_usd":None,"source_content_sha256":financial_hash},
        "production":{"status":"unknown_build_rebuild_concierge_and_content_production","amount_usd":None,"source_content_sha256":exit_hash or primary_hash},
    }
    ledger=json.loads((ROOT/"evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text()); matches=[row for row in ledger["records"] if row.get("company")=="RightMessage"]; hashes=[row["source_content_sha256"] for row in captured]
    duplicate={"source_unified_review_ledger_sha256":ledger["content_sha256"],"company_match_count":len(matches),"company_match_review_packet_ids":[row["review_packet_id"] for row in matches],"exact_content_mirror_detected":len(hashes)!=len(set(hashes)),"additional_case_episode_collision_detected":len(matches)>1}
    primary_markers={row["marker"] for row in by_role.get("founder_interview_2026",{}).get("targeted_claim_windows",[])}; financial_markers={row["marker"] for row in by_role.get("independent_financial_interview",{}).get("targeted_claim_windows",[])}; exit_markers={row["marker"] for row in by_role.get("cofounder_exit_account",{}).get("targeted_claim_windows",[])}
    outcome_bound="$30k MRR" in primary_markers and "roughly a year" in primary_markers
    resource_bound="half a million" in financial_markers and "expenses are probably 20k" in financial_markers and "$700k investment" in exit_markers
    gates={"named_company_product_motion_audience":"evidence_ready","exact_subvertical_classification":"evidence_ready","observed_period_and_recency":"evidence_ready_current_turnaround_with_historical_lineage","market_scale_and_lifecycle":"evidence_ready_small_multi_market_growth","source_bound_budget_tier":"evidence_ready_mixed_budget_from_500k_to_700k_capital_and_20k_monthly_expense_snapshot" if resource_bound else "blocked","six_cost_components":"evidence_ready_all_six_recorded_without_zero_cost_inference","result_claim_binding":"evidence_ready_founder_stated_turnaround_not_audited" if outcome_bound else "blocked","independent_outcome_surface":"evidence_ready_four_independent_revenue_and_scale_surfaces_not_audit" if len(independent)>=4 else "blocked","entity_and_episode_resolution":"evidence_ready_two_founders_original_launch_failure_and_rebuild_timeline" if {"founder_interview_2026","cofounder_exit_account","official_pricing"}.issubset(by_role) else "blocked","cross_platform_duplicate_review":"evidence_ready_machine_screen" if not duplicate["exact_content_mirror_detected"] and not duplicate["additional_case_episode_collision_detected"] else "pending_named_review","named_human_exact_binding":"pending_named_review"}
    ready=sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload={"schema":"ProofLaunchGTMRightMessageAdmissionDossierV2","company":"RightMessage","legal_entity_hint":"RightMessage, Inc.","founder_identity":"Brennan Dunn and Shai Schechter","entity_key":"entity-"+hashlib.sha256(b"rightmessage inc|rightmessage|brennan dunn|shai schechter").hexdigest()[:20],"episode_key":"episode-"+hashlib.sha256(b"rightmessage|original launch failure rebuild turnaround|2017-01-01|2026-04-03").hexdigest()[:20],"provisional_subvertical_id":"b2b.martech_sales_tech.marketing_automation","episode_definition":"2017 to April 2026 launch, funded team expansion, plateau and near-bankruptcy, then solo-led rebuild to founder-stated roughly USD 30K MRR within about one year.","source_count":len(records),"captured_source_count":len(captured),"independent_captured_source_count":len(independent),"cost_components":costs,"budget_context":{"historical_capital_floor_usd":500000,"cofounder_later_investment_recollection_usd":700000,"historical_monthly_total_expense_estimate_usd":20000,"complete_episode_total_unknown":True},"duplicate_screen":duplicate,"gate_count":len(gates),"evidence_ready_gate_count":ready,"blocking_gate_count":len(gates)-ready,"gates":gates,"sources":records,"observed_named_human_review_count":0,"formal_candidate_quota_credit":0,"automatic_promotion_allowed":False,"truth_boundary":"The roughly USD 30K MRR turnaround is founder-stated and unaudited. Historical sources conflict between roughly USD 500K raised and a later USD 700K investment recollection; both are preserved. A historical interview estimates USD 20K monthly total expenses, but no component allocation or complete episode total is invented. This is mixed-budget turnaround evidence, not zero-budget or causal proof."}
    payload["content_sha256"]=_digest(payload); atomic_write_text(OUTPUT,json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"output":str(OUTPUT),"captured_source_count":len(captured),"independent_captured_source_count":len(independent),"ready_gates":ready,"blocking_gates":len(gates)-ready,"content_sha256":payload["content_sha256"]},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
