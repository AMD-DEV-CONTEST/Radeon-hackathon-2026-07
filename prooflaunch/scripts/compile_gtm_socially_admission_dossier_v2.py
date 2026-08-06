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
OUTPUT = ROOT / "evidence/v10/gtm-socially-admission-dossier-v2.json"
SOURCES = (
    ("independent_financial_profile", "https://www.indiehackers.com/post/money/37-year-old-bootstrapped-startup-founder-on-saving-smartly-not-aggressively-P8x3S4aA2SR2hp02x54o", True),
    ("independent_company_interview", "https://www.siliconluxembourg.lu/from-managed-services-to-global-impact-razrtech-journey-in-luxembourg-and-beyond/", True),
    ("independent_business_reconstruction", "https://www.starterstory.com/razrtech-breakdown", True),
    ("founder_progress_update", "https://www.indiehackers.com/product/socially-the-community-builder-platform/1-year-9-months-we-are-going-strong--O5s4oZCcl382qAEHQn9", False),
    ("official_product", "https://socially.so/", False),
    ("official_launch_syndication", "https://techsense.lu/news/introducing-socially-a-saas-based-social-networking-platform", False),
    ("independent_founder_identity", "https://www.siliconluxembourg.lu/words-from-a-member-anshul-gupta-razrcorp/", True),
)
MARKERS = {
    "independent_financial_profile": ("$12-18K", "$2000", "$2200", "$7000", "$500", "$1MM", "150,000 users", "bootstrapped"),
    "independent_company_interview": ("revenue from IT services", "flagship product, Socially", "payment methods", "virtual currency", "customizations"),
    "independent_business_reconstruction": ("$83.3K", "$2000/month", "$2200 annually", "$7000/month", "$500/month", "81"),
    "founder_progress_update": ("275 communities", "USA", "UK", "Canada", "Europe", "Australia", "didnt believe in raising cash"),
    "official_product": ("community", "memberships", "events", "custom"),
    "official_launch_syndication": ("NICHE communities", "native iOS and Android apps", "monetisation", "socially.lu"),
    "independent_founder_identity": ("Anshul Gupta", "started RazrCorp in 2016", "Vodafone", "Arcelor Mittal"),
}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag.casefold() in {"script", "style", "svg", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag):
        if tag.casefold() in {"script", "style", "svg", "noscript"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data):
        if not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _windows(body: str, markers: tuple[str, ...]) -> list[dict[str, str]]:
    parser = _Text()
    parser.feed(body)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    lower = text.casefold()
    rows = []
    for marker in markers:
        index = lower.find(marker.casefold())
        if index >= 0:
            excerpt = text[max(0, index - 100):min(len(text), index + len(marker) + 220)].strip()
            rows.append({"marker": marker, "bounded_exact_excerpt": excerpt, "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fetch(url: str):
    last = None
    for _ in range(3):
        try:
            return default_fetch(url, timeout=30.0)
        except Exception as error:
            last = error
    raise last


def main() -> int:
    robots = RobotsPermissionCache()
    records = []
    for role, url, independent in SOURCES:
        robots_status, allowed = robots.check(url)
        if not allowed:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "blocked_by_robots", "robots_status": robots_status})
            continue
        try:
            response = _fetch(url)
            body = response.body.decode("utf-8", errors="replace")
            surfaces = extract_claim_surfaces(body)
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "captured_and_bounded", "robots_status": robots_status, "captured_at": datetime.now(timezone.utc).isoformat(), "source_content_sha256": hashlib.sha256(response.body).hexdigest(), "page_title": surfaces["page_title"], "page_description": surfaces["page_description"], "fragment_counts": surfaces["fragment_counts"], "fragments": surfaces["fragments"], "targeted_claim_windows": _windows(body, MARKERS.get(role, ())), "raw_page_retained": False})
        except Exception as error:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "capture_failed", "robots_status": robots_status, "error_type": type(error).__name__, "error_summary": str(error)[:240]})

    captured = [row for row in records if row["capture_status"] == "captured_and_bounded"]
    by_role = {row["source_role"]: row for row in captured}
    independent = [row for row in captured if row["independent"]]
    primary = by_role.get("independent_financial_profile", {})
    primary_hash = primary.get("source_content_sha256", "")
    primary_markers = {row["marker"] for row in primary.get("targeted_claim_windows", [])}
    founder_markers = {row["marker"] for row in by_role.get("founder_progress_update", {}).get("targeted_claim_windows", [])}
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    matches = [row for row in ledger["records"] if row.get("company") == "Socially"]
    hashes = [row["source_content_sha256"] for row in captured]
    duplicate = {"source_unified_review_ledger_sha256": ledger["content_sha256"], "company_match_count": len(matches), "company_match_review_packet_ids": [row["review_packet_id"] for row in matches], "exact_content_mirror_detected": len(hashes) != len(set(hashes)), "additional_case_episode_collision_detected": len(matches) > 1}
    outcome_bound = {"$12-18K", "$1MM", "150,000 users"}.issubset(primary_markers) and "275 communities" in founder_markers
    resource_bound = {"$2000", "$2200", "$7000", "$500", "bootstrapped"}.issubset(primary_markers)
    costs = {
        "paid_media": {"status": "unknown_no_complete_paid_media_ledger_public", "amount_usd": None, "source_content_sha256": primary_hash},
        "personnel": {"status": "known_monthly_team_salary_snapshot", "amount_usd": 7000, "source_content_sha256": primary_hash},
        "tools": {"status": "known_monthly_software_subscription_snapshot", "amount_usd": 500, "source_content_sha256": primary_hash},
        "creators": {"status": "unknown_founder_community_and_content_labor_not_separately_priced", "amount_usd": None, "source_content_sha256": primary_hash},
        "channel_fees": {"status": "unknown_payment_lifetime_deal_and_enterprise_sales_fees", "amount_usd": None, "source_content_sha256": primary_hash},
        "production": {"status": "known_monthly_aws_plus_annual_cloudflare_infrastructure_snapshot", "amount_usd": None, "source_content_sha256": primary_hash},
    }
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_2023_to_2024_twelve_to_twenty_four_months",
        "market_scale_and_lifecycle": "evidence_ready_small_multi_market_growth",
        "source_bound_budget_tier": "evidence_ready_capital_efficient_with_line_item_monthly_snapshot" if resource_bound else "blocked",
        "six_cost_components": "evidence_ready_all_six_recorded_with_three_unknowns_and_no_zero_cost_inference",
        "result_claim_binding": "evidence_ready_founder_reported_revenue_users_and_community_scale_not_audited" if outcome_bound else "blocked",
        "independent_outcome_surface": "evidence_ready_four_independent_identity_financial_or_scale_surfaces_not_audit" if len(independent) >= 4 else "blocked",
        "entity_and_episode_resolution": "evidence_ready_razrtech_operator_socially_product_boundary_preserved" if {"official_product", "independent_founder_identity", "independent_company_interview"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate["exact_content_mirror_detected"] and not duplicate["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload = {
        "schema": "ProofLaunchGTMSociallyAdmissionDossierV2",
        "company": "RazrTech / Socially",
        "legal_entity_hint": "RazrCorp operator; Socially product brand",
        "founder_identity": "Anshul Gupta",
        "entity_key": "entity-" + hashlib.sha256(b"razrcorp|razrtech|socially|anshul gupta").hexdigest()[:20],
        "episode_key": "episode-" + hashlib.sha256(b"socially|slow bootstrapped community growth|2023-01-01|2024-09-28").hexdigest()[:20],
        "provisional_subvertical_id": "b2b.b2b_saas.horizontal_saas",
        "episode_definition": "2023 through September 2024 bootstrapped Socially product growth under RazrTech, with subscription, lifetime-deal, custom-feature and enterprise deployment revenue and a public operating-cost snapshot.",
        "source_count": len(records), "captured_source_count": len(captured), "independent_captured_source_count": len(independent),
        "cost_components": costs,
        "budget_context": {"monthly_revenue_range_usd": [12000, 18000], "annual_revenue_claim_usd": 1000000, "monthly_aws_usd": 2000, "annual_cloudflare_usd": 2200, "monthly_team_salaries_usd": 7000, "monthly_tools_usd": 500, "complete_episode_total_unknown": True},
        "duplicate_screen": duplicate,
        "gate_count": len(gates), "evidence_ready_gate_count": ready, "blocking_gate_count": len(gates) - ready, "gates": gates, "sources": records,
        "observed_named_human_review_count": 0, "formal_candidate_quota_credit": 0, "automatic_promotion_allowed": False,
        "truth_boundary": "The USD 12K-18K monthly and USD 1M annual figures are public founder-reported claims, not audited accounts. The annual figure includes a few enterprise on-premise clients and must not be treated as subscription MRR. RazrTech is the operator and Socially is the product; their scopes are preserved. The cost snapshot supports capital-efficient, not zero-budget, classification; paid media, creator, channel and complete production totals remain unknown.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "captured_source_count": len(captured), "independent_captured_source_count": len(independent), "ready_gates": ready, "blocking_gates": len(gates) - ready, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
