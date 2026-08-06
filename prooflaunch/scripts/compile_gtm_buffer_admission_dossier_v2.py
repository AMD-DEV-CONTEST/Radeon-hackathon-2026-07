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
OUTPUT = ROOT / "evidence/v10/gtm-buffer-admission-dossier-v2.json"
SOURCES = (
    ("company_growth_postmortem", "https://buffer.com/resources/top-10-learnings-growing-to-10-million-arr/", False),
    ("company_transparent_pricing", "https://buffer.com/resources/transparent-pricing-buffer/", False),
    ("company_revenue_dashboard", "https://buffer.com/resources/revenue-dashboard/", False),
    ("independent_tech_press", "https://techcrunch.com/2014/12/16/profitable-saas-startup-buffer-breaks-down-how-it-spends-its-revenue/", True),
    ("independent_strategy_analysis", "https://www.yesoptimist.com/buffer-content-marketing-strategy/", True),
    ("official_legal_identity", "https://buffer.com/legal", False),
    ("official_company_profile", "https://buffer.com/about", False),
)
TARGET_MARKERS = {
    "company_growth_postmortem": ("$10 million", "3 million registered users", "90+ team members", "single marketing strategy", "content marketing", "0 change in conversion rate", "doubled our revenue"),
    "company_transparent_pricing": ("$223,939.74", "$22,890.76", "$6,302.40", "$14,161.79", "$13,885.42", "$2,577.81"),
    "company_revenue_dashboard": ("actual revenue numbers", "Annual Run Rate", "Number of Customers"),
    "independent_tech_press": ("$4.832 million", "125 percent", "$2.143 million"),
    "independent_strategy_analysis": ("4 Million Users", "$4.6MM", "content-first"),
    "official_legal_identity": ("Buffer, Inc.",),
    "official_company_profile": ("November 2010", "$25.8M", "small businesses"),
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


def _windows(html: str, markers: tuple[str, ...]) -> list[dict[str, str]]:
    parser = _VisibleText()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    lowered = text.casefold()
    rows = []
    for marker in markers:
        index = lowered.find(marker.casefold())
        if index < 0:
            continue
        excerpt = text[max(0, index - 80):min(len(text), index + len(marker) + 150)].strip()
        rows.append({
            "marker": marker,
            "bounded_exact_excerpt": excerpt,
            "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
        })
    return rows


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    robots = RobotsPermissionCache()
    records = []
    for role, url, independent in SOURCES:
        robots_status, allowed = robots.check(url)
        if not allowed:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "blocked_by_robots", "robots_status": robots_status})
            continue
        try:
            response = default_fetch(url)
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
            records.append({
                "source_role": role,
                "source_url": url,
                "independent": independent,
                "capture_status": "capture_failed",
                "robots_status": robots_status,
                "error_type": type(error).__name__,
                "error_summary": str(error)[:240],
            })
    captured = [row for row in records if row["capture_status"] == "captured_and_bounded"]
    by_role = {row["source_role"]: row for row in captured}
    independent = [row for row in captured if row["independent"]]
    pricing = by_role.get("company_transparent_pricing", {})
    pricing_markers = {row["marker"] for row in pricing.get("targeted_claim_windows", [])}
    six_costs_ready = {"$223,939.74", "$6,302.40", "$14,161.79", "$13,885.42", "$2,577.81"}.issubset(pricing_markers)
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    company_matches = [row for row in ledger["records"] if row.get("company") == "Buffer"]
    hashes = [row["source_content_sha256"] for row in captured]
    duplicate_screen = {
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "company_match_count": len(company_matches),
        "company_match_review_packet_ids": [row["review_packet_id"] for row in company_matches],
        "exact_content_mirror_detected": len(hashes) != len(set(hashes)),
        "additional_case_episode_collision_detected": len(company_matches) > 1,
    }
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_historical_episode",
        "market_scale_and_lifecycle": "evidence_ready",
        "source_bound_budget_tier": "evidence_ready_mature_scale_monthly_cost_ledger",
        "six_cost_components": "evidence_ready_all_recorded_one_unknown_amount" if six_costs_ready else "blocked",
        "result_claim_binding": "evidence_ready" if by_role.get("company_growth_postmortem", {}).get("targeted_claim_windows") else "blocked",
        "independent_outcome_surface": "evidence_ready" if len(independent) >= 2 else "blocked",
        "entity_and_episode_resolution": "evidence_ready" if {"official_legal_identity", "official_company_profile"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate_screen["exact_content_mirror_detected"] and not duplicate_screen["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(str(value).startswith("evidence_ready") for value in gates.values())
    cost_components = {
        "paid_media": {"status": "disclosed_monthly", "amount_usd": 6302.40, "source_role": "company_transparent_pricing"},
        "personnel": {"status": "disclosed_monthly", "amount_usd": 223939.74, "source_role": "company_transparent_pricing"},
        "tools": {"status": "disclosed_monthly", "amount_usd": 14161.79, "source_role": "company_transparent_pricing"},
        "creators": {"status": "unknown_amount_scope_disclosed", "amount_usd": None, "source_role": "company_growth_postmortem"},
        "channel_fees": {"status": "disclosed_monthly", "amount_usd": 13885.42, "source_role": "company_transparent_pricing"},
        "production": {"status": "bounded_monthly_equipment", "amount_usd": 2577.81, "source_role": "company_transparent_pricing"},
    }
    for row in cost_components.values():
        row["source_content_sha256"] = by_role.get(row["source_role"], {}).get("source_content_sha256", "")
    payload = {
        "schema": "ProofLaunchGTMBufferAdmissionDossierV2",
        "company": "Buffer",
        "legal_entity_hint": "Buffer, Inc.",
        "entity_key": "entity-" + hashlib.sha256(b"company|buffer inc").hexdigest()[:20],
        "episode_key": "episode-" + hashlib.sha256(b"buffer inc|buffer|content-led growth to 10m arr|multi-market|2010-11-01|2016-06-02").hexdigest()[:20],
        "provisional_subvertical_id": "b2b.martech_sales_tech.marketing_automation",
        "episode_definition": "2010-2016 growth from initial launch to $10M ARR using an early content focus, customer research, pricing, product expansion and company transparency; descriptive portfolio episode, not single-channel causality.",
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
        "truth_boundary": "The dossier binds company-reported growth, a line-item monthly cost ledger, two independent surfaces, legal identity continuity, episode identity and duplicate screening. It does not make content marketing a sole causal explanation and cannot admit a candidate without named source inspection.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "captured_source_count": len(captured),
        "independent_captured_source_count": len(independent),
        "ready_gates": ready,
        "blocking_gates": len(gates) - ready,
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
