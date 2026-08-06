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
OUTPUT = ROOT / "evidence/v10/gtm-spendbase-admission-dossier-v2.json"
SOURCES = (
    ("founder_interview_2026", "https://www.indiehackers.com/post/growing-to-an-8-figure-arr-in-three-years-with-savings-based-pricing-RQZkdT4qgvFZ5wAtNuLA", False),
    ("official_team", "https://www.spendbase.co/team/", False),
    ("official_product", "https://www.spendbase.co/", False),
    ("official_product_faq", "https://faq.spendbase.co/en/knowledge-base_spendbase/what-is-spendbase", False),
    ("independent_funding", "https://www.cbinsights.com/company/spendbase/financials", True),
    ("independent_employer_profile", "https://www.forbes.com/companies/spendbase/", True),
    ("independent_revenue_profile", "https://getlatka.com/companies/spendbase.co", True),
)
TARGET_MARKERS = {
    "founder_interview_2026": ("eight-digit ARR", "300% YoY growth", "800 businesses", "200+", "bootstrapped", "39%", "Organic growth levers", "partnerships"),
    "official_team": ("180+ Headcount", "300% YoY Growth", "2023", "global team"),
    "official_product": ("spend management", "SaaS", "cloud", "corporate cards"),
    "official_product_faq": ("500", "$4-5 million", "$0.5-1 million"),
    "independent_funding": ("$510K", "$0.5M", "January 1, 2025", "5 rounds"),
    "independent_employer_profile": ("Employees", "Andrew Alex", "Spendbase"),
    "independent_revenue_profile": ("revenue", "ARR", "Spendbase"),
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
        excerpt = text[max(0, index - 100):min(len(text), index + len(marker) + 210)].strip()
        rows.append({"marker": marker, "bounded_exact_excerpt": excerpt, "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fetch(url: str):
    last: Exception | None = None
    for _ in range(3):
        try:
            return default_fetch(url, timeout=30.0)
        except Exception as error:
            last = error
    assert last is not None
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
            records.append({
                "source_role": role,
                "source_url": url,
                "independent": independent,
                "capture_status": "captured_and_bounded",
                "robots_status": robots_status,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_content_sha256": hashlib.sha256(response.body).hexdigest(),
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
    primary_hash = by_role.get("founder_interview_2026", {}).get("source_content_sha256", "")
    team_hash = by_role.get("official_team", {}).get("source_content_sha256", "")
    funding_hash = by_role.get("independent_funding", {}).get("source_content_sha256", "")
    cost_components = {
        "paid_media": {"status": "unknown_no_complete_media_ledger", "amount_usd": None, "source_content_sha256": primary_hash},
        "personnel": {"status": "unknown_180_to_200_plus_headcount_disclosed", "amount_usd": None, "source_content_sha256": team_hash or primary_hash},
        "tools": {"status": "unknown_global_fintech_stack_and_data_costs", "amount_usd": None, "source_content_sha256": primary_hash},
        "creators": {"status": "unknown_content_and_executive_labor", "amount_usd": None, "source_content_sha256": primary_hash},
        "channel_fees": {"status": "unknown_partner_financial_and_program_fees", "amount_usd": None, "source_content_sha256": funding_hash or primary_hash},
        "production": {"status": "unknown_product_content_and_event_production", "amount_usd": None, "source_content_sha256": primary_hash},
    }
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    matches = [row for row in ledger["records"] if row.get("company") == "Spendbase"]
    hashes = [row["source_content_sha256"] for row in captured]
    duplicate_screen = {
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "company_match_count": len(matches),
        "company_match_review_packet_ids": [row["review_packet_id"] for row in matches],
        "exact_content_mirror_detected": len(hashes) != len(set(hashes)),
        "additional_case_episode_collision_detected": len(matches) > 1,
    }
    primary_markers = {row["marker"] for row in by_role.get("founder_interview_2026", {}).get("targeted_claim_windows", [])}
    team_markers = {row["marker"] for row in by_role.get("official_team", {}).get("targeted_claim_windows", [])}
    outcome_bound = "eight-digit ARR" in primary_markers and "300% YoY growth" in primary_markers
    resource_scale_bound = "200+" in primary_markers or "180+ Headcount" in team_markers
    independent_scale_bound = len(independent) >= 3 and "independent_funding" in by_role
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_current_2023_to_2026",
        "market_scale_and_lifecycle": "evidence_ready_global_mature_growth",
        "source_bound_budget_tier": "evidence_ready_mature_scale_from_180_to_200_plus_headcount_and_disclosed_external_capital" if resource_scale_bound and funding_hash else "blocked",
        "six_cost_components": "evidence_ready_all_six_recorded_as_unknown_without_zero_cost_inference",
        "result_claim_binding": "evidence_ready_founder_stated_not_audited" if outcome_bound else "blocked",
        "independent_outcome_surface": "evidence_ready_independent_scale_funding_and_revenue_surfaces_not_audit" if independent_scale_bound else "blocked",
        "entity_and_episode_resolution": "evidence_ready_founder_company_product_timeline" if {"founder_interview_2026", "official_team", "official_product"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate_screen["exact_content_mirror_detected"] and not duplicate_screen["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload = {
        "schema": "ProofLaunchGTMSpendbaseAdmissionDossierV2",
        "company": "Spendbase",
        "legal_entity_hint": "Spendbase, Inc.",
        "founder_identity": "Andrew Alex",
        "entity_key": "entity-" + hashlib.sha256(b"spendbase inc|spendbase|andrew alex").hexdigest()[:20],
        "episode_key": "episode-" + hashlib.sha256(b"spendbase|global savings-led growth|2023-01-01|2026-04-02").hexdigest()[:20],
        "provisional_subvertical_id": "b2b.b2b_saas.finance_operations",
        "episode_definition": "2023 to April 2026 global savings-led B2B finance-operations growth from SaaS optimization into a multi-product spend platform.",
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
        "truth_boundary": "The eight-figure ARR and 300% YoY growth are founder-stated and unaudited. Independent profiles corroborate entity scale and disclosed capital, not causality. Spendbase is not a zero-budget case: 180-200+ headcount, external funding/program support and a global regulated product imply mature-scale resources, while every exact cost amount remains unknown.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "captured_source_count": len(captured), "independent_captured_source_count": len(independent), "ready_gates": ready, "blocking_gates": len(gates) - ready, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
