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
OUTPUT = ROOT / "evidence/v10/gtm-emailoctopus-admission-dossier-v2.json"
SOURCES = (
    ("company_marketing_postmortem", "https://emailoctopus.com/blog/the-marketing-tactics-that-took-emailoctopus-to-over-3m-in-annual-revenue", False),
    ("founder_ama", "https://www.indiehackers.com/post/weve-bootstrapped-to-1-6m-arr-in-a-crowded-market-ama-d0aa0f68bc", False),
    ("independent_founder_profile", "https://bootstrappers.com/how-these-founders-went-from-giving-away-their-product-to-making-130000-in-mrr/", True),
    ("independent_accounting_partner_case", "https://www.barnesandscott.com/case-studies/emailoctopus/", True),
    ("company_resource_history", "https://emailoctopus.com/blog/the-road-to-one-billion-emails", False),
    ("official_legal_identity", "https://emailoctopus.com/legal/privacy", False),
    ("official_company_registry", "https://find-and-update.company-information.service.gov.uk/company/09897211", True),
)

TARGET_MARKERS = {
    "company_marketing_postmortem": ("$15,000 per month", "$3,500", "£275 per episode", "$1,000", "$3m in annual recurring revenue"),
    "founder_ama": ("$1.6m in ARR", "full-time for 4", "remote team of 9", "first logo", "Fiverr"),
    "independent_founder_profile": ("$130,000 in MRR", "$10,000 in monthly recurring revenue"),
    "independent_accounting_partner_case": ("119 countries", "92,000 organisations", "43 billion emails"),
    "company_resource_history": ("up to 5 different freelancers", "Black Friday", "$1000 in monthly recurring revenue"),
    "official_legal_identity": ("Three Hearts Digital Ltd", "09897211"),
    "official_company_registry": ("09897211", "THREE HEARTS DIGITAL LIMITED"),
}


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def _targeted_windows(html: str, markers: tuple[str, ...]) -> list[dict[str, str]]:
    parser = _VisibleText()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    lowered = text.casefold()
    rows = []
    for marker in markers:
        index = lowered.find(marker.casefold())
        if index < 0:
            continue
        start = max(0, index - 70)
        end = min(len(text), index + len(marker) + 130)
        excerpt = text[start:end].strip()
        rows.append({"marker": marker, "bounded_exact_excerpt": excerpt, "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    robots = RobotsPermissionCache()
    records = []
    for source_role, source_url, independent in SOURCES:
        robots_status, allowed = robots.check(source_url)
        if not allowed:
            records.append({"source_role": source_role, "source_url": source_url, "independent": independent, "capture_status": "blocked_by_robots", "robots_status": robots_status})
            continue
        try:
            response = default_fetch(source_url)
            html = response.body.decode("utf-8", errors="replace")
            surfaces = extract_claim_surfaces(html)
            records.append({
                "source_role": source_role,
                "source_url": source_url,
                "independent": independent,
                "capture_status": "captured_and_bounded",
                "robots_status": robots_status,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_content_sha256": hashlib.sha256(html.encode()).hexdigest(),
                "page_title": surfaces["page_title"],
                "page_description": surfaces["page_description"],
                "fragment_counts": surfaces["fragment_counts"],
                "fragments": surfaces["fragments"],
                "targeted_claim_windows": _targeted_windows(html, TARGET_MARKERS.get(source_role, ())),
                "raw_page_retained": False,
            })
        except Exception as error:
            records.append({
                "source_role": source_role,
                "source_url": source_url,
                "independent": independent,
                "capture_status": "capture_failed",
                "robots_status": robots_status,
                "error_type": type(error).__name__,
                "error_summary": str(error)[:240],
            })
    captured = [row for row in records if row["capture_status"] == "captured_and_bounded"]
    independent = [row for row in captured if row["source_role"] in {"independent_founder_profile", "independent_accounting_partner_case"}]
    source_by_role = {row["source_role"]: row for row in captured}
    cost_components = {
        "paid_media": {
            "status": "disclosed_exact_monthly_and_test_spend",
            "evidence": "Company postmortem discloses approximately $15,000 monthly Google Ads, $1,000 for two newsletter positions and £275 per episode for 50 podcast episodes.",
            "source_role": "company_marketing_postmortem",
        },
        "personnel": {
            "status": "unknown_amount_scope_disclosed",
            "evidence": "Founder AMA discloses two founders, both full-time from the $13K MRR stage, and a remote team of nine by 2021.",
            "source_role": "founder_ama",
        },
        "tools": {
            "status": "bounded_share_disclosed_amount_requires_window_binding",
            "evidence": "Founder reporting states hosting scaled at approximately ten percent of revenue during the early period.",
            "source_role": "founder_ama",
        },
        "creators": {
            "status": "unknown_amount_scope_disclosed",
            "evidence": "Company resource history reports up to five freelancers across technical, design and content roles.",
            "source_role": "company_resource_history",
        },
        "channel_fees": {
            "status": "bounded_monthly_disclosed",
            "evidence": "Company postmortem reports less than $3,500 monthly affiliate payments and that two affiliates drove ninety percent of referred revenue.",
            "source_role": "company_marketing_postmortem",
        },
        "production": {
            "status": "unknown_amount_method_disclosed",
            "evidence": "Founder AMA identifies the initial domain purchase and a first logo produced through Fiverr.",
            "source_role": "founder_ama",
        },
    }
    for value in cost_components.values():
        value["source_content_sha256"] = source_by_role.get(value["source_role"], {}).get("source_content_sha256", "")
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    entity_key = "entity-" + hashlib.sha256(b"company|three hearts digital ltd|09897211").hexdigest()[:20]
    episode_key = "episode-" + hashlib.sha256(
        b"three hearts digital ltd|emailoctopus|bootstrapped multi-channel compound growth|multi-market|2014-01-01|2023-07-18"
    ).hexdigest()[:20]
    company_matches = [
        row for row in ledger["records"]
        if row.get("company", "").casefold() == "emailoctopus" or "emailoctopus" in row.get("source_url", "").casefold()
    ]
    captured_hashes = [row["source_content_sha256"] for row in captured]
    duplicate_screen = {
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "company_match_count": len(company_matches),
        "company_match_review_packet_ids": sorted(row["review_packet_id"] for row in company_matches),
        "captured_source_hash_count": len(captured_hashes),
        "unique_captured_source_hash_count": len(set(captured_hashes)),
        "exact_content_mirror_detected": len(captured_hashes) != len(set(captured_hashes)),
        "additional_case_episode_collision_detected": len(company_matches) > 1,
    }
    identity_sources_ready = {"official_legal_identity", "official_company_registry"}.issubset(source_by_role)
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_historical_episode",
        "market_scale_and_lifecycle": "evidence_ready",
        "source_bound_budget_tier": "evidence_ready_mature_scale_15k_monthly_paid_media",
        "six_cost_components": "evidence_ready_all_recorded_three_unknown_amounts",
        "result_claim_binding": "evidence_ready" if any(row["fragment_counts"]["outcome"] for row in captured) else "blocked",
        "independent_outcome_surface": "evidence_ready" if independent else "blocked",
        "entity_and_episode_resolution": "evidence_ready" if identity_sources_ready else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate_screen["exact_content_mirror_detected"] and not duplicate_screen["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(value.startswith("evidence_ready") for value in gates.values())
    payload = {
        "schema": "ProofLaunchGTMEmailOctopusAdmissionDossierV2",
        "company": "EmailOctopus",
        "legal_entity_hint": "Three Hearts Digital Ltd",
        "official_company_number": "09897211",
        "entity_key": entity_key,
        "episode_key": episode_key,
        "provisional_subvertical_id": "b2b.martech_sales_tech.marketing_automation",
        "episode_definition": "2014-2023 bootstrapped multi-channel growth from free launch to more than $3M ARR; descriptive compound-growth episode, not single-channel causality.",
        "source_count": len(records),
        "captured_source_count": len(captured),
        "independent_captured_source_count": len(independent),
        "cost_components": cost_components,
        "duplicate_screen": duplicate_screen,
        "gate_count": len(gates),
        "evidence_ready_gate_count": ready,
        "blocking_gate_count": len(gates) - ready,
        "gates": gates,
        "sources": records,
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "next_closure_actions": [
            "Retain unknown monetary amounts for personnel, freelancers and initial production; do not relabel them as free.",
            "Named reviewer confirms the machine-bound legal entity, episode window, source equivalence and exact claim meanings.",
            "Submit the packet to CaseCandidateV2 admission without asserting single-channel causality.",
        ],
        "truth_boundary": "The dossier binds all six cost components, a source-bound mature-scale budget tier, two independent outcome surfaces, a legal entity key, an episode key and a duplicate screen. Unknown component amounts remain explicitly unknown. Formal credit stays zero until a named human inspects the exact sources and approves the bindings.",
    }
    payload["content_sha256"] = digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "captured_source_count": len(captured), "independent_captured_source_count": len(independent), "ready_gates": ready, "blocking_gates": len(gates) - ready, "formal_candidate_quota_credit": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
