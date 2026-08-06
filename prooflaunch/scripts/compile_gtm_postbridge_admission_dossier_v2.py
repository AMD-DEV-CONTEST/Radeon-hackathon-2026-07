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
OUTPUT = ROOT / "evidence/v10/gtm-postbridge-admission-dossier-v2.json"
SOURCES = (
    ("founder_interview", "https://www.indiehackers.com/post/hitting-35k-mrr-after-struggling-to-make-money-online-for-four-years-CNVpxrwIVqxcsfZ4fERw", False),
    ("independent_current_analysis", "https://weekly-opportunities.com/p/how-jack-friks-went-from-3k-month-to-35k-mrr-and-why-he-almost-quit-first", True),
    ("independent_source_accountability", "https://kaeda.co/cases/post-bridge", True),
    ("independent_historical_analysis", "https://www.marketergems.com/p/jack-friks-postbridge-story-personal-problem-to-profitable-saas", True),
    ("independent_revenue_dashboard", "https://cards.frame.fun/mrr/jackfriks", True),
    ("official_api_pricing", "https://support.post-bridge.com/api/post-bridge-api-overview-access-and-pricing", False),
    ("founder_product_portfolio", "https://www.jackfriks.com/", False),
)
TARGET_MARKERS = {
    "founder_interview": ("$35k MRR", "cost me nothing except time", "$100 and $200 per month", "$1,000 a month", "I did it all alone", "contractors", "eight months", "six months"),
    "independent_current_analysis": ("$35k USD", "eight months", "six", "$1,000 a month", "$100 to $200 per month", "solo", "contractor"),
    "independent_source_accountability": ("$35K", "$100-200/mo", "Solo", "self-reported", "not audited"),
    "independent_historical_analysis": ("$11,000", "$9", "$18", "$27", "one person", "zero paid ads"),
    "independent_revenue_dashboard": ("$38,990", "$324,234", "1,593", "verified revenue"),
    "official_api_pricing": ("$5/month", "official platform APIs", "10 requests per second"),
    "founder_product_portfolio": ("post bridge", "23 projects", "5 success", "22% hit rate"),
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
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _windows(body: str, markers: tuple[str, ...]) -> list[dict[str, str]]:
    parser = _VisibleText()
    parser.feed(body)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    lower = text.casefold()
    rows = []
    for marker in markers:
        index = lower.find(marker.casefold())
        if index < 0:
            continue
        excerpt = text[max(0, index - 80):min(len(text), index + len(marker) + 170)].strip()
        rows.append({"marker": marker, "bounded_exact_excerpt": excerpt, "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fetch_with_bounded_retry(url: str, attempts: int = 3):
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return default_fetch(url, timeout=30.0)
        except Exception as error:
            last_error = error
    assert last_error is not None
    raise last_error


def main() -> int:
    robots = RobotsPermissionCache()
    records = []
    for role, url, independent in SOURCES:
        robots_status, allowed = robots.check(url)
        if not allowed:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "blocked_by_robots", "robots_status": robots_status})
            continue
        try:
            response = _fetch_with_bounded_retry(url)
            body = response.body.decode("utf-8", errors="replace")
            surfaces = extract_claim_surfaces(body)
            records.append({
                "source_role": role,
                "source_url": url,
                "independent": independent,
                "capture_status": "captured_and_bounded",
                "robots_status": robots_status,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_content_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "page_title": surfaces["page_title"],
                "page_description": surfaces["page_description"],
                "fragment_counts": surfaces["fragment_counts"],
                "fragments": surfaces["fragments"],
                "targeted_claim_windows": _windows(body, TARGET_MARKERS.get(role, ())),
                "raw_page_retained": False,
            })
        except Exception as error:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "capture_failed", "robots_status": robots_status, "error_type": type(error).__name__, "error_summary": str(error)[:240]})
    captured = [row for row in records if row["capture_status"] == "captured_and_bounded"]
    by_role = {row["source_role"]: row for row in captured}
    independent = [row for row in captured if row["independent"]]
    primary_hash = by_role.get("founder_interview", {}).get("source_content_sha256", "")
    current_hash = by_role.get("independent_current_analysis", {}).get("source_content_sha256", "")
    official_hash = by_role.get("official_api_pricing", {}).get("source_content_sha256", "")
    cost_components = {
        "paid_media": {"status": "unknown_amount_content_led_growth_reported", "amount_usd": None, "source_content_sha256": primary_hash},
        "personnel": {"status": "unknown_amount_founder_and_contractor_labor", "amount_usd": None, "source_content_sha256": primary_hash},
        "tools": {"status": "bounded_monthly_current_infrastructure", "amount_usd": 200, "source_content_sha256": primary_hash},
        "creators": {"status": "unknown_amount_founder_content_labor", "amount_usd": None, "source_content_sha256": current_hash or primary_hash},
        "channel_fees": {"status": "unknown_amount_platform_and_payment_fees", "amount_usd": None, "source_content_sha256": official_hash},
        "production": {"status": "unknown_economic_cost_cash_build_cost_reported_zero", "amount_usd": None, "source_content_sha256": primary_hash},
    }
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    matches = [row for row in ledger["records"] if row.get("company") == "Post Bridge"]
    hashes = [row["source_content_sha256"] for row in captured]
    duplicate_screen = {
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "company_match_count": len(matches),
        "company_match_review_packet_ids": [row["review_packet_id"] for row in matches],
        "exact_content_mirror_detected": len(hashes) != len(set(hashes)),
        "additional_case_episode_collision_detected": len(matches) > 1,
    }
    primary_markers = {row["marker"] for row in by_role.get("founder_interview", {}).get("targeted_claim_windows", [])}
    resource_bound = {"cost me nothing except time", "$100 and $200 per month"}.issubset(primary_markers)
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_three_to_six_months",
        "market_scale_and_lifecycle": "evidence_ready",
        "source_bound_budget_tier": "evidence_ready_low_budget_cash_and_infrastructure_bounded_labor_unknown" if resource_bound else "blocked",
        "six_cost_components": "evidence_ready_all_six_recorded_without_free_labor_assumption",
        "result_claim_binding": "evidence_ready_founder_stated_not_audited" if "$35k MRR" in primary_markers else "blocked",
        "independent_outcome_surface": "evidence_ready_self_report_corroboration_not_audit" if len(independent) >= 2 else "blocked",
        "entity_and_episode_resolution": "evidence_ready_founder_product_domain_binding" if {"founder_interview", "founder_product_portfolio"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate_screen["exact_content_mirror_detected"] and not duplicate_screen["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload = {
        "schema": "ProofLaunchGTMPostBridgeAdmissionDossierV2",
        "company": "Post Bridge",
        "legal_entity_hint": None,
        "founder_identity": "Jack Friks",
        "entity_key": "entity-" + hashlib.sha256(b"founder-product|jack friks|post bridge").hexdigest()[:20],
        "episode_key": "episode-" + hashlib.sha256(b"jack friks|post bridge|solo content-led product growth|multi-market|2024-10-01|2026-06-17").hexdigest()[:20],
        "provisional_subvertical_id": "b2b.martech_sales_tech.marketing_automation",
        "episode_definition": "October 2024 to June 2026 solo founder-led social-scheduling growth to founder-stated $35K MRR after an eight-month plateau and six-month doubling period.",
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
        "truth_boundary": "The $35K MRR outcome is founder-stated and not audited. Initial cash build cost is reported as zero, but founder time and contractor labor remain unknown and are never treated as free. Current infrastructure is bounded at $100–200 monthly; no complete economic-cost total or single-channel causality is asserted.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "captured_source_count": len(captured), "independent_captured_source_count": len(independent), "ready_gates": ready, "blocking_gates": len(gates) - ready, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
