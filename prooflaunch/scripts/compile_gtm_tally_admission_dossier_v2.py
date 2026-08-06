#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
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
DOSSIER_OUTPUT = ROOT / "evidence/v10/gtm-tally-admission-dossier-v2.json"
LEDGER_OUTPUT = ROOT / "evidence/v10/gtm-tally-supplemental-review-ledger-v2.json"
SOURCES = (
    ("official_20k_cost_boundary", "https://blog.tally.so/bootstrapping-our-saas-from-10k-to-20k-mrr/", False),
    ("official_30k_zero_spend", "https://blog.tally.so/year-2-bootstrapping-our-saas-to-30k-mrr/", False),
    ("independent_failory_interview", "https://www.failory.com/interview/tally", True),
    ("independent_latka_interview", "https://getlatka.com/companies/tally-forms", True),
    ("official_company_identity", "https://tally.so/about", False),
    ("independent_firstmillion_reconstruction", "https://www.firstmillion.club/p/tally", True),
    ("official_later_resource_boundary", "https://blog.tally.so/a-letter-to-our-future-marketing-manager/", False),
)
MARKERS = {
    "official_20k_cost_boundary": ("$20,700 MRR", "36,560 total users", "We haven't spent money (yet) on paid advertising", "does not include salaries", "recurring monthly costs"),
    "official_30k_zero_spend": ("$30K MRR milestone", "zero marketing spend", "team of 2 co-founders", "50.000 creators"),
    "independent_failory_interview": ("$6,000 MRR", "12,600 users", "completely independent", "cold outreach"),
    "independent_latka_interview": ("$50k MRR", "without any budget", "product-led growth", "Recorded Mar 17, 2023"),
    "official_company_identity": ("Filip Minev", "Marie Martens", "bootstrapped and funded by our customers"),
    "independent_firstmillion_reconstruction": ("$4M+ in ARR", "Zero marketing spend", "16,000+ paying customers", "800,000+ users"),
    "official_later_resource_boundary": ("didn't really run ads", "won't inherit a marketing budget", "mostly through word of mouth", "4 full-time and 5 part-time"),
}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]; self.suppressed=0
    def handle_starttag(self, tag, attrs):
        if tag.casefold() in {"script","style","svg","noscript"}: self.suppressed += 1
    def handle_endtag(self, tag):
        if tag.casefold() in {"script","style","svg","noscript"} and self.suppressed: self.suppressed -= 1
    def handle_data(self, data):
        if not self.suppressed:
            value=" ".join(data.split())
            if value: self.parts.append(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _windows(body, markers):
    parser=_Text(); parser.feed(body); text=re.sub(r"\s+", " ", " ".join(parser.parts)).strip(); lower=text.casefold(); rows=[]
    for marker in markers:
        index=lower.find(marker.casefold())
        if index >= 0:
            excerpt=text[max(0,index-110):min(len(text),index+len(marker)+240)].strip()
            rows.append({"marker":marker,"bounded_exact_excerpt":excerpt,"excerpt_sha256":hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows


def _fetch(url):
    last=None
    for _ in range(3):
        try: return default_fetch(url, timeout=30.0)
        except Exception as error: last=error
    raise last


def _supplemental_ledger(dossier):
    primary=next(row for row in dossier["sources"] if row["source_role"]=="official_20k_cost_boundary")
    packet={
        "review_packet_id":"unified-"+_digest("tally-replacement:"+dossier["episode_key"])[:20],
        "origin_kind":"replacement_transparency_packet",
        "origin_source":"evidence/v10/gtm-tally-admission-dossier-v2.json",
        "origin_id":dossier["episode_key"],
        "origin_ledger_sha256":dossier["content_sha256"],
        "origin_packet_sha256":_digest({"episode_key":dossier["episode_key"],"primary":primary["source_content_sha256"]}),
        "source_url":primary["source_url"],
        "company":"Tally",
        "title":"2020-2022 zero-paid product-led form-builder growth",
        "source_excerpt":" | ".join(row["bounded_exact_excerpt"] for row in primary["targeted_claim_windows"]),
        "provisional_subvertical_ids":["b2b.b2b_saas.horizontal_saas"],
        "machine_ready_for_named_review":True,
        "status":"ready_for_named_review",
        "source_capture_status":"captured_and_bounded",
        "source_capture_sha256":primary["source_content_sha256"],
        "candidate_gate_blockers":["named_human_exact_binding"],
        "review_priority_score":100,
        "proposed_field_values":{}, "claim_fragments":{},
        "corroboration_queries":["Tally 2022 MRR independent interview","Tally zero marketing spend independent"],
        "human_source_inspection_completed":False,"named_reviewer":None,"formal_candidate_quota_credit":0,"automatic_promotion_allowed":False,
    }
    payload={
        "schema":"ProofLaunchGTMAllSubverticalUnifiedReviewLedgerV2",
        "source_ledger_sha256s":[dossier["content_sha256"]],
        "review_packet_count":1,"machine_ready_for_named_review_count":1,"evidence_gap_count":0,
        "represented_subvertical_count":1,"represented_subvertical_ids":["b2b.b2b_saas.horizontal_saas"],
        "origin_counts":{"replacement_transparency_packet":1},"observed_named_human_review_count":0,
        "formal_candidate_quota_credit":0,"automatic_promotion_allowed":False,"records":[packet],
        "truth_boundary":"Supplemental one-case review ledger for the qualified Tally replacement. It creates review work only; named human inspection and independent admission remain mandatory.",
    }
    payload["content_sha256"]=_digest(payload); return payload


def main():
    robots=RobotsPermissionCache(); records=[]
    for role,url,independent in SOURCES:
        status,allowed=robots.check(url)
        if not allowed:
            records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"blocked_by_robots","robots_status":status}); continue
        try:
            response=_fetch(url); body=response.body.decode("utf-8",errors="replace"); surfaces=extract_claim_surfaces(body)
            records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"captured_and_bounded","robots_status":status,"captured_at":datetime.now(timezone.utc).isoformat(),"source_content_sha256":hashlib.sha256(response.body).hexdigest(),"page_title":surfaces["page_title"],"page_description":surfaces["page_description"],"fragment_counts":surfaces["fragment_counts"],"fragments":surfaces["fragments"],"targeted_claim_windows":_windows(body,MARKERS[role]),"raw_page_retained":False})
        except Exception as error:
            records.append({"source_role":role,"source_url":url,"independent":independent,"capture_status":"capture_failed","robots_status":status,"error_type":type(error).__name__,"error_summary":str(error)[:240]})
    captured=[row for row in records if row["capture_status"]=="captured_and_bounded"]; by_role={row["source_role"]:row for row in captured}; independent=[row for row in captured if row["independent"]]
    primary_markers={row["marker"] for row in by_role.get("official_20k_cost_boundary",{}).get("targeted_claim_windows",[])}
    year2_markers={row["marker"] for row in by_role.get("official_30k_zero_spend",{}).get("targeted_claim_windows",[])}
    outcome_ready={"$20,700 MRR","36,560 total users"}.issubset(primary_markers) and "$30K MRR milestone" in year2_markers
    resource_ready={"We haven't spent money (yet) on paid advertising","does not include salaries"}.issubset(primary_markers) and "zero marketing spend" in year2_markers
    main_ledger=json.loads((ROOT/"evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    matches=[row for row in main_ledger["records"] if row.get("company")=="Tally"]
    hashes=[row["source_content_sha256"] for row in captured]
    duplicate={"source_unified_review_ledger_sha256":main_ledger["content_sha256"],"company_match_count":len(matches),"company_match_review_packet_ids":[row["review_packet_id"] for row in matches],"exact_content_mirror_detected":len(hashes)!=len(set(hashes)),"additional_case_episode_collision_detected":len(matches)>0}
    gates={
        "named_company_product_motion_audience":"evidence_ready",
        "exact_subvertical_classification":"evidence_ready",
        "observed_period_and_recency":"evidence_ready_2020_to_2022_twenty_four_plus_months",
        "market_scale_and_lifecycle":"evidence_ready_small_europe_growth",
        "source_bound_budget_tier":"evidence_ready_zero_paid_media_only_not_zero_total_cost" if resource_ready else "blocked",
        "six_cost_components":"evidence_ready_all_six_recorded_with_five_unknowns_and_explicit_salary_exclusion",
        "result_claim_binding":"evidence_ready_founder_reported_20k_to_30k_mrr_and_user_scale_not_audited" if outcome_ready else "blocked",
        "independent_outcome_surface":"evidence_ready_three_independent_interview_or_reconstruction_surfaces_not_audit" if len(independent)>=3 else "blocked",
        "entity_and_episode_resolution":"evidence_ready_tally_form_builder_and_founders_resolved" if {"official_company_identity","independent_failory_interview"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review":"evidence_ready_machine_screen" if not duplicate["exact_content_mirror_detected"] and not duplicate["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding":"pending_named_review",
    }
    ready=sum(str(value).startswith("evidence_ready") for value in gates.values())
    primary_hash=by_role.get("official_20k_cost_boundary",{}).get("source_content_sha256","")
    costs={
        "paid_media":{"status":"known_zero_for_observed_episode","amount_usd":0,"source_content_sha256":primary_hash},
        "personnel":{"status":"unknown_explicitly_excluded_from_public_cost_overview","amount_usd":None,"source_content_sha256":primary_hash},
        "tools":{"status":"unknown_exact_image_line_items_not_promoted_from_unreadable_visual","amount_usd":None,"source_content_sha256":primary_hash},
        "creators":{"status":"unknown_founder_content_and_community_labor_not_priced","amount_usd":None,"source_content_sha256":primary_hash},
        "channel_fees":{"status":"unknown_payment_and_partner_fees_not_completely_disclosed","amount_usd":None,"source_content_sha256":primary_hash},
        "production":{"status":"unknown_complete_hosting_product_and_creative_total","amount_usd":None,"source_content_sha256":primary_hash},
    }
    payload={
        "schema":"ProofLaunchGTMTallyAdmissionDossierV2","company":"Tally BV","product":"Tally form builder","founder_identity":"Marie Martens and Filip Minev",
        "entity_key":"entity-"+hashlib.sha256(b"tally bv|tally form builder|marie martens|filip minev").hexdigest()[:20],
        "episode_key":"episode-"+hashlib.sha256(b"tally|zero-paid product-led growth|2020-09-01|2022-10-10").hexdigest()[:20],
        "provisional_subvertical_id":"b2b.b2b_saas.horizontal_saas",
        "episode_definition":"September 2020 through October 2022 bootstrapped, zero-paid-media product-led growth from launch to USD 30K MRR, using a generous free tier, product badge, search, founder outreach, community and support.",
        "source_count":len(records),"captured_source_count":len(captured),"independent_captured_source_count":len(independent),
        "cost_components":costs,"budget_context":{"paid_advertising_usd":0,"paid_media_scope":"observed episode only","founder_salary_and_tax_excluded":True,"complete_episode_total_unknown":True},
        "duplicate_screen":duplicate,"gate_count":len(gates),"evidence_ready_gate_count":ready,"blocking_gate_count":len(gates)-ready,"gates":gates,"sources":records,
        "observed_named_human_review_count":0,"formal_candidate_quota_credit":0,"automatic_promotion_allowed":False,
        "truth_boundary":"Zero-paid means known-zero paid advertising for the bounded 2020-2022 episode, not zero total cost. Salaries and taxes were explicitly excluded; founder labor, tools, channel fees and full production costs remain unknown. Revenue and user counts are founder reported, not audited, and later sources corroborate continuity rather than causality.",
    }
    payload["content_sha256"]=_digest(payload); atomic_write_text(DOSSIER_OUTPUT,json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    ledger=_supplemental_ledger(payload); atomic_write_text(LEDGER_OUTPUT,json.dumps(ledger,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"dossier":str(DOSSIER_OUTPUT),"ledger":str(LEDGER_OUTPUT),"captured":len(captured),"independent":len(independent),"ready_gates":ready,"blocking_gates":len(gates)-ready,"dossier_sha256":payload["content_sha256"],"ledger_sha256":ledger["content_sha256"]},sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
